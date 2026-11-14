"""Customers quote, place, view and cancel their orders
(UR-007, UR-008, UR-012, UR-013, Business Rules 1 & 9)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import CustomerUser, DbSession
from app.models import Order
from app.models.enums import OrderStatus, OtpPurpose
from app.schemas.driver import DriverInfoOut, HandoverOut, OtpOut
from app.services import audit, otp
from app.services.jobs import ACTIVE_JOB
from app.schemas.orders import (
    AddressOut,
    CancelIn,
    LineOut,
    OrderIn,
    OrderOut,
    OrderPage,
    OrderSummaryOut,
    QuoteOut,
    SealOut,
    StatusEventOut,
    TripOut,
)
from app.services import orders as order_service

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _address(o: Order, prefix: str) -> AddressOut:
    return AddressOut(**{f: getattr(o, f"{prefix}_{f}") for f in AddressOut.model_fields})


def _summary(o: Order) -> dict:
    return dict(
        id=o.id, order_number=o.order_number, status=o.status, business_id=o.business_id,
        business_name=o.business.business_name, total_cents=o.total_cents,
        is_estimate=o.is_estimate,
        collection_window_start=o.collection_window_start,
        collection_window_end=o.collection_window_end,
        delivery_window_start=o.delivery_window_start,
        delivery_window_end=o.delivery_window_end,
        created_at=o.created_at,
    )


def order_out(o: Order) -> OrderOut:
    return OrderOut(
        **_summary(o),
        items=[LineOut.model_validate(i) for i in o.items],
        subtotal_cents=o.subtotal_cents,
        delivery_fee_cents=o.delivery_fee_cents,
        distance_km=o.distance_km,
        collection_address=_address(o, "collection"),
        delivery_address=_address(o, "delivery"),
        notes=o.customer_notes,
        cancelled_reason=o.cancelled_reason,
        declined_reason=o.declined_reason,
        history=[StatusEventOut.model_validate(e) for e in o.events],
        driver=_current_driver(o),
        handovers=[HandoverOut.model_validate(h) for h in o.handovers],
        seals=[SealOut.model_validate(s) for s in o.seals],
        paid_cents=o.paid_cents,
        adjustment_cents=o.adjustment_cents,
        final_total_cents=o.final_total_cents,
        balance_cents=o.balance_cents,
        trips=[TripOut(job_id=j.id, kind=j.kind, status=j.status.value,
                       driver_first_name=j.driver.full_name.split()[0] if j.driver else None)
               for j in o.jobs],
    )


def _current_driver(o: Order) -> DriverInfoOut | None:
    job = next((j for j in o.jobs if j.status in ACTIVE_JOB and j.driver), None)
    if job is None:
        return None
    d = job.driver
    profile = d.driver_profile
    return DriverInfoOut(
        first_name=d.full_name.split()[0], phone=d.phone,
        vehicle_type=profile.vehicle_type if profile else None,
        vehicle_registration=profile.vehicle_registration if profile else None,
        job_kind=job.kind,
    )


def _own_order(db: DbSession, customer: CustomerUser, order_id: uuid.UUID,
               lock: bool = False) -> Order:
    order = db.get(Order, order_id, with_for_update=lock)
    # Business Rule 9: other customers' orders don't exist as far as you know
    if order is None or order.customer_id != customer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order


@router.post("/quote", response_model=QuoteOut)
def quote_order(body: OrderIn, customer: CustomerUser, db: DbSession) -> QuoteOut:
    """Price and check an order without placing it – for the checkout screen."""
    q = order_service.quote(db, body)
    return QuoteOut(
        items=[
            LineOut(service_id=l.service.id, service_name=l.service.name,
                    category=l.service.category, pricing_unit=l.service.pricing_unit,
                    unit_price_cents=l.service.price_cents, quantity=l.quantity,
                    line_total_cents=l.total)
            for l in q.lines
        ],
        subtotal_cents=q.subtotal_cents,
        delivery_fee_cents=q.delivery_fee_cents,
        total_cents=q.total_cents,
        distance_km=q.distance_km,
        is_estimate=q.is_estimate,
        earliest_delivery=q.earliest_delivery,
    )


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def place_order(
    body: OrderIn, customer: CustomerUser, db: DbSession, request: Request
) -> OrderOut:
    """Place an order. Prices come from the laundry's current catalog and are
    frozen on the order; any price sent by the client is rejected."""
    order = order_service.place(db, customer, body, request)
    return order_out(order)


@router.get("", response_model=OrderPage)
def my_orders(
    customer: CustomerUser,
    db: DbSession,
    status_: Annotated[OrderStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrderPage:
    """Your order history, newest first (UR-013)."""
    where = [Order.customer_id == customer.id]
    if status_:
        where.append(Order.status == status_)
    total = db.scalar(select(func.count()).select_from(Order).where(*where))
    rows = db.scalars(select(Order).where(*where)
                      .order_by(Order.created_at.desc(), Order.id).limit(limit).offset(offset))
    return OrderPage(items=[OrderSummaryOut(**_summary(o)) for o in rows],
                     total=total, limit=limit, offset=offset)


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: uuid.UUID, customer: CustomerUser, db: DbSession) -> OrderOut:
    """Full order with its status history, for tracking (UR-012)."""
    return order_out(_own_order(db, customer, order_id))


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: uuid.UUID, customer: CustomerUser, db: DbSession, request: Request,
    body: CancelIn | None = None,
) -> OrderOut:
    """Cancel before the laundry has been collected."""
    order = _own_order(db, customer, order_id, lock=True)
    order_service.cancel(db, order, customer, body.reason if body else None, request)
    return order_out(order)


# ---------- One-time codes (SEC-005 – SEC-008) ----------

# Which code the customer needs depends on where the order is
_CODE_STAGE = {
    OrderStatus.ACCEPTED: OtpPurpose.COLLECTION,
    OrderStatus.OUT_FOR_DELIVERY: OtpPurpose.DELIVERY,
}


def _stage(order: Order) -> OtpPurpose:
    purpose = _CODE_STAGE.get(order.status)
    if purpose is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No code is needed for this order right now")
    return purpose


@router.get("/{order_id}/otp", response_model=OtpOut)
def get_code(order_id: uuid.UUID, customer: CustomerUser, db: DbSession) -> OtpOut:
    """The code to give the driver – only when they arrive, never over the phone."""
    order = _own_order(db, customer, order_id)
    purpose = _stage(order)
    current = otp.active(db, order, purpose)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Your code was used or locked. Generate a new one")
    return OtpOut(purpose=purpose, code=otp.code_for(current), expires_at=current.expires_at)


@router.post("/{order_id}/otp/regenerate", response_model=OtpOut)
def regenerate_code(
    order_id: uuid.UUID, customer: CustomerUser, db: DbSession, request: Request
) -> OtpOut:
    """New code (e.g. after it expired or locked). The old one stops working."""
    order = _own_order(db, customer, order_id, lock=True)
    purpose = _stage(order)
    fresh = otp.issue(db, order, purpose)
    audit.record(db, "otp.regenerated", actor_id=customer.id, entity_type="order",
                 entity_id=order.id, details={"purpose": purpose.value}, request=request)
    db.commit()
    return OtpOut(purpose=purpose, code=otp.code_for(fresh), expires_at=fresh.expires_at)
