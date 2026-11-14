"""A laundry business works through its incoming orders (UR-010, UR-011, SEC-017).

Only verified businesses (Business Rule 2) and only their own orders
(Business Rule 8) – another business's order returns 404.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import DbSession, require_business_staff
from app.api.routes.orders import _summary, order_out
from app.models import BusinessStaff, Order
from app.models.enums import OrderStatus
from app.schemas.orders import (
    BusinessOrderOut,
    DeclineIn,
    OrderPage,
    OrderSummaryOut,
    ReceiveIn,
    StaffEventOut,
    StatusChangeIn,
    StatusCounts,
)
from app.schemas.engagement import WeighIn
from app.services import jobs
from app.services import orders as order_service

router = APIRouter(prefix="/api/business/orders", tags=["business orders"])

Staff = Annotated[BusinessStaff, Depends(require_business_staff())]

# Orders that still need something done; finished ones are filtered out by default
ACTIVE = [
    OrderStatus.PLACED, OrderStatus.ACCEPTED, OrderStatus.COLLECTED, OrderStatus.RECEIVED,
    OrderStatus.PROCESSING, OrderStatus.READY, OrderStatus.OUT_FOR_DELIVERY,
]


def business_order_out(o: Order) -> BusinessOrderOut:
    base = order_out(o).model_dump(exclude={"history"})
    history = []
    for e in o.events:
        actor = e.actor
        role = None
        if actor is not None:
            # Staff show as owner/manager/attendant; anyone else by platform role
            m = actor.staff_membership
            role = (m.staff_role.value if m and m.business_id == o.business_id
                    else actor.role.value)
        history.append(StaffEventOut(
            from_status=e.from_status, to_status=e.to_status, note=e.note,
            created_at=e.created_at,
            actor_name=actor.full_name if actor else None, actor_role=role,
        ))
    return BusinessOrderOut(
        **base,
        customer_name=o.customer.full_name,
        customer_phone=o.customer.phone,
        history=history,
    )


def _own_order(db: DbSession, staff: BusinessStaff, order_id: uuid.UUID,
               lock: bool = False) -> Order:
    order = db.get(Order, order_id, with_for_update=lock)
    if order is None or order.business_id != staff.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    return order


@router.get("", response_model=OrderPage)
def list_orders(
    staff: Staff,
    db: DbSession,
    status_: Annotated[list[OrderStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrderPage:
    """Your business's orders, soonest collection first. Defaults to active
    orders; pass ?status=delivered&status=cancelled etc. to see others."""
    where = [Order.business_id == staff.business_id, Order.status.in_(status_ or ACTIVE)]
    total = db.scalar(select(func.count()).select_from(Order).where(*where))
    rows = db.scalars(
        select(Order).where(*where)
        .order_by(Order.collection_window_start, Order.id).limit(limit).offset(offset)
    )
    return OrderPage(items=[OrderSummaryOut(**_summary(o)) for o in rows],
                     total=total, limit=limit, offset=offset)


@router.get("/summary", response_model=StatusCounts)
def order_counts(staff: Staff, db: DbSession) -> StatusCounts:
    """How many orders are in each state – for the dashboard."""
    rows = db.execute(
        select(Order.status, func.count())
        .where(Order.business_id == staff.business_id)
        .group_by(Order.status)
    ).all()
    counts = {s: 0 for s in OrderStatus}
    counts.update({s: n for s, n in rows})
    return StatusCounts(counts=counts)


@router.get("/{order_id}", response_model=BusinessOrderOut)
def get_order(order_id: uuid.UUID, staff: Staff, db: DbSession) -> BusinessOrderOut:
    return business_order_out(_own_order(db, staff, order_id))


@router.post("/{order_id}/accept", response_model=BusinessOrderOut)
def accept_order(
    order_id: uuid.UUID, staff: Staff, db: DbSession, request: Request
) -> BusinessOrderOut:
    order = _own_order(db, staff, order_id, lock=True)
    order_service.accept(db, order, staff.user, request)
    return business_order_out(order)


@router.post("/{order_id}/decline", response_model=BusinessOrderOut)
def decline_order(
    order_id: uuid.UUID, body: DeclineIn, staff: Staff, db: DbSession, request: Request
) -> BusinessOrderOut:
    """Decline a new order. The reason is shown to the customer."""
    order = _own_order(db, staff, order_id, lock=True)
    order_service.decline(db, order, staff.user, body.reason, request)
    return business_order_out(order)


@router.post("/{order_id}/receive", response_model=BusinessOrderOut)
def receive_order(
    order_id: uuid.UUID, body: ReceiveIn, staff: Staff, db: DbSession, request: Request
) -> BusinessOrderOut:
    """The driver drops off a bag: scan its QR code and check its seals to
    confirm you received this order (SEC-011, SEC-014, SEC-027, UAT-008).
    A failed seal check still completes the handover but opens an incident."""
    order = _own_order(db, staff, order_id, lock=True)
    _, incident = jobs.receive(db, order, staff.user, body.code, body.seal_numbers,
                               body.seals_intact, request)
    db.refresh(order)
    out = business_order_out(order)
    out.seal_incident_reference = incident.reference if incident else None
    return out


@router.post("/{order_id}/weigh", response_model=BusinessOrderOut)
def weigh_order(
    order_id: uuid.UUID, body: WeighIn, staff: Staff, db: DbSession, request: Request
) -> BusinessOrderOut:
    """Record the real weight of the per-kg items. If it costs more than the
    estimate, the customer is asked to pay the balance before delivery."""
    order = _own_order(db, staff, order_id, lock=True)
    actual = {line.service_id: line.actual_quantity for line in body.lines}
    if len(actual) != len(body.lines):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Each item only once")
    order_service.weigh(db, order, staff.user, actual, request)
    return business_order_out(order)


@router.post("/{order_id}/status", response_model=BusinessOrderOut)
def change_order_status(
    order_id: uuid.UUID, body: StatusChangeIn, staff: Staff, db: DbSession, request: Request
) -> BusinessOrderOut:
    """Move an order you've received through processing → ready."""
    order = _own_order(db, staff, order_id, lock=True)
    order_service.advance(db, order, body.status, staff.user, body.note, request)
    return business_order_out(order)
