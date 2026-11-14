"""Pricing, scheduling and placing orders (UR-007, UR-008, SEC-009, SEC-042).

Every amount is computed here from the database – the client only says which
services and how many. The result is frozen onto the order.
"""

import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    BusinessProfile,
    LaundryService,
    Order,
    OrderAdjustment,
    OrderItem,
    OrderStatusEvent,
    User,
)
from app.models.enums import OrderStatus, PricingUnit
from app.schemas.orders import OrderAddress, OrderIn, TimeWindow
from app.schemas.business import format_rands
from app.services import audit, jobs, notifications
from app.services.order_status import change_status, label
from app.services.search import get_bookable, haversine_km

SAST = timezone(timedelta(hours=2), "SAST")  # South Africa has no daylight saving
_ORDER_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U

# Customers may cancel until the laundry has been collected
CANCELLABLE = {OrderStatus.PLACED, OrderStatus.ACCEPTED}


def _invalid(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


def new_order_number() -> str:
    return "LC-" + "".join(secrets.choice(_ORDER_ALPHABET) for _ in range(8))


@dataclass
class Line:
    service: LaundryService
    quantity: int

    @property
    def total(self) -> int:
        return self.service.price_cents * self.quantity


@dataclass
class Quote:
    business: BusinessProfile
    lines: list[Line]
    subtotal_cents: int
    delivery_fee_cents: int
    total_cents: int
    distance_km: float
    is_estimate: bool
    earliest_delivery: datetime


# ---------- Validation ----------

def _check_window(window: TimeWindow, label: str) -> None:
    length = (window.end - window.start).total_seconds() / 60
    if not settings.slot_min_minutes <= length <= settings.slot_max_minutes:
        raise _invalid(f"The {label} window must be between {settings.slot_min_minutes} "
                       f"and {settings.slot_max_minutes} minutes long")
    start, end = window.start.astimezone(SAST), window.end.astimezone(SAST)
    day_start = start.replace(hour=settings.slot_day_start_hour, minute=0, second=0, microsecond=0)
    day_end = start.replace(hour=settings.slot_day_end_hour, minute=0, second=0, microsecond=0)
    if start < day_start or end > day_end:
        raise _invalid(f"The {label} window must fall between "
                       f"{settings.slot_day_start_hour:02d}:00 and "
                       f"{settings.slot_day_end_hour:02d}:00 (South African time)")


def _check_schedule(data: OrderIn, slowest_hours: int, now: datetime) -> datetime:
    """Returns the earliest moment delivery could start."""
    collect = data.collection_window
    earliest = now + timedelta(minutes=settings.order_min_lead_minutes)
    if collect.start < earliest:
        raise _invalid(f"Collection must start at least {settings.order_min_lead_minutes} "
                       "minutes from now")
    if collect.start > now + timedelta(days=settings.order_max_days_ahead):
        raise _invalid(f"Collection can be booked at most {settings.order_max_days_ahead} "
                       "days ahead")
    _check_window(collect, "collection")
    _check_window(data.delivery_window, "delivery")

    earliest_delivery = collect.end + timedelta(hours=slowest_hours)
    if data.delivery_window.start < earliest_delivery:
        raise _invalid(
            "Delivery can't start before your laundry is ready. Earliest delivery: "
            + earliest_delivery.astimezone(SAST).strftime("%a %d %b %Y %H:%M SAST")
        )
    return earliest_delivery


def _lines(db: Session, business: BusinessProfile, data: OrderIn) -> list[Line]:
    ids = [i.service_id for i in data.items]
    services = {s.id: s for s in db.scalars(select(LaundryService).where(
        LaundryService.id.in_(ids),
        LaundryService.business_id == business.id,
        LaundryService.is_active.is_(True),
    ))}
    lines = []
    for item in data.items:
        service = services.get(item.service_id)
        if service is None:
            raise _invalid("One of the chosen services isn't available at this laundry")
        if item.quantity < service.min_quantity:
            unit = service.pricing_unit.value.removeprefix("per_")
            raise _invalid(f"{service.name} has a minimum of {service.min_quantity} {unit}")
        lines.append(Line(service, item.quantity))
    return lines


def delivery_fee(distance_km: float) -> int:
    return settings.delivery_base_fee_cents + settings.delivery_fee_per_km_cents * math.ceil(
        distance_km)


def quote(db: Session, data: OrderIn, now: datetime | None = None) -> Quote:
    now = now or datetime.now(UTC)
    business = get_bookable(db, data.business_id)
    if business is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Laundry not found")

    lines = _lines(db, business, data)
    earliest_delivery = _check_schedule(
        data, max(l.service.turnaround_hours for l in lines), now)

    collect = data.collection_address
    deliver = data.delivery_address or collect
    to_laundry = haversine_km(collect.latitude, collect.longitude,
                              business.latitude, business.longitude)
    if to_laundry > settings.max_collection_distance_km:
        raise _invalid(f"This laundry only collects within "
                       f"{settings.max_collection_distance_km:g} km "
                       f"(your address is {to_laundry:.1f} km away)")
    back = haversine_km(business.latitude, business.longitude,
                        deliver.latitude, deliver.longitude)
    if back > settings.max_collection_distance_km:
        raise _invalid(f"This laundry only delivers within "
                       f"{settings.max_collection_distance_km:g} km")
    distance = round(to_laundry + back, 2)

    subtotal = sum(l.total for l in lines)
    fee = delivery_fee(distance)
    return Quote(
        business=business,
        lines=lines,
        subtotal_cents=subtotal,
        delivery_fee_cents=fee,
        total_cents=subtotal + fee,
        distance_km=distance,
        is_estimate=any(l.service.pricing_unit == PricingUnit.PER_KG for l in lines),
        earliest_delivery=earliest_delivery,
    )


# ---------- Placing and cancelling ----------

def _address_fields(prefix: str, a: OrderAddress) -> dict:
    return {f"{prefix}_{k}": v for k, v in a.model_dump().items()}


def place(db: Session, customer: User, data: OrderIn, request: Request) -> Order:
    q = quote(db, data)
    deliver = data.delivery_address or data.collection_address

    # 32^8 ≈ 1 trillion possible numbers, so a clash is very unlikely; the
    # unique constraint is the final guard against the rare race.
    number = new_order_number()
    while db.scalar(select(Order.id).where(Order.order_number == number)):
        number = new_order_number()

    order = Order(
        order_number=number,
        customer_id=customer.id,
        business_id=q.business.id,
        status=OrderStatus.PLACED,
        **_address_fields("collection", data.collection_address),
        **_address_fields("delivery", deliver),
        collection_window_start=data.collection_window.start,
        collection_window_end=data.collection_window.end,
        delivery_window_start=data.delivery_window.start,
        delivery_window_end=data.delivery_window.end,
        customer_notes=data.notes,
        subtotal_cents=q.subtotal_cents,
        delivery_fee_cents=q.delivery_fee_cents,
        total_cents=q.total_cents,
        distance_km=q.distance_km,
        is_estimate=q.is_estimate,
    )
    order.items = [
        OrderItem(
            service_id=l.service.id, position=i, service_name=l.service.name,
            category=l.service.category, pricing_unit=l.service.pricing_unit,
            unit_price_cents=l.service.price_cents,
            turnaround_hours=l.service.turnaround_hours,
            quantity=l.quantity, line_total_cents=l.total,
        )
        for i, l in enumerate(q.lines)
    ]
    order.events = [OrderStatusEvent(to_status=OrderStatus.PLACED, actor_user_id=customer.id)]
    db.add(order)
    db.flush()

    audit.record(db, "order.placed", actor_id=customer.id, entity_type="order",
                 entity_id=order.id,
                 details={"order_number": order.order_number, "total_cents": order.total_cents,
                          "business_id": str(order.business_id)},
                 request=request)
    db.commit()
    return order



# Steps a laundry business may move an order through itself (UR-011).
# Collection and receipt are handovers, confirmed by OTP / QR scan in a later
# phase (SEC-007, SEC-011), so they are deliberately not in this table.
BUSINESS_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.RECEIVED: {OrderStatus.PROCESSING},
    OrderStatus.PROCESSING: {OrderStatus.READY},
}


_label = label


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail)


def accept(db: Session, order: Order, staff_user: User, request: Request) -> None:
    if order.status != OrderStatus.PLACED:
        raise _conflict(f"Only new orders can be accepted; this one is {_label(order.status)}")
    if order.collection_window_start <= datetime.now(UTC):
        raise _conflict("The collection time has already passed; decline the order instead")
    if settings.require_payment_before_acceptance and order.paid_cents < order.total_cents:
        raise _conflict("The customer hasn't paid for this order yet")
    change_status(db, order, OrderStatus.ACCEPTED, staff_user)
    jobs.on_order_accepted(db, order)  # collection job + collection OTP
    notifications.customer(db, order, "order.accepted", "Order accepted",
                           f"{order.business.business_name} accepted order "
                           f"{order.order_number}. We'll let you know when a driver is on "
                           "the way.")
    audit.record(db, "order.accepted", actor_id=staff_user.id, entity_type="order",
                 entity_id=order.id, details={"order_number": order.order_number},
                 request=request)
    db.commit()
    db.refresh(order)


def decline(db: Session, order: Order, staff_user: User, reason: str, request: Request) -> None:
    if order.status != OrderStatus.PLACED:
        raise _conflict(f"Only new orders can be declined; this one is {_label(order.status)}")
    order.declined_reason = reason
    change_status(db, order, OrderStatus.DECLINED, staff_user, reason)
    notifications.customer(db, order, "order.declined", "Order declined",
                           f"{order.business.business_name} couldn't take order "
                           f"{order.order_number}: {reason}"
                           + (" Your payment will be refunded." if order.paid_cents else ""))
    _flag_refund(db, order, staff_user, request)
    audit.record(db, "order.declined", actor_id=staff_user.id, entity_type="order",
                 entity_id=order.id,
                 details={"order_number": order.order_number, "reason": reason},
                 request=request)
    db.commit()
    db.refresh(order)


def advance(db: Session, order: Order, to: OrderStatus, staff_user: User, note: str | None,
            request: Request) -> None:
    allowed = BUSINESS_TRANSITIONS.get(order.status, set())
    if to not in allowed:
        raise _conflict(f"An order that is {_label(order.status)} can't be marked {_label(to)}")
    if to == OrderStatus.READY and order.is_estimate:
        raise _conflict("Weigh the per-kg items before marking the order ready")
    if to == OrderStatus.READY and order.balance_cents > 0:
        raise _conflict(f"The customer still owes {format_rands(order.balance_cents)} "
                        "after weighing. They've been asked to pay it")
    previous = order.status
    change_status(db, order, to, staff_user, note)
    if to == OrderStatus.READY:
        jobs.on_order_ready(db, order)  # delivery job goes on the board
        notifications.customer(db, order, "order.ready", "Your laundry is clean",
                               f"Order {order.order_number} is ready. A driver will bring "
                               "it to you in your delivery window.")
    audit.record(db, "order.status_changed", actor_id=staff_user.id, entity_type="order",
                 entity_id=order.id,
                 details={"order_number": order.order_number, "from": previous.value,
                          "to": to.value},
                 request=request)
    db.commit()
    db.refresh(order)


def cancel(db: Session, order: Order, customer: User, reason: str | None,
           request: Request) -> None:
    if order.status not in CANCELLABLE:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"An order that is {order.status.value.replace('_', ' ')} "
                            "can no longer be cancelled")
    previous = order.status
    order.cancelled_reason = reason
    drivers = [j.driver for j in order.jobs if j.status in jobs.ACTIVE_JOB]
    change_status(db, order, OrderStatus.CANCELLED, customer, reason)
    jobs.on_order_cancelled(db, order)
    notifications.notify(db, [*notifications.business_team(db, order.business_id), *drivers],
                         "order.cancelled", "Order cancelled",
                         f"Order {order.order_number} was cancelled by the customer.",
                         order=order)
    _flag_refund(db, order, customer, request)
    audit.record(db, "order.cancelled", actor_id=customer.id, entity_type="order",
                 entity_id=order.id,
                 details={"order_number": order.order_number, "previous_status": previous.value},
                 request=request)
    db.commit()
    db.refresh(order)


def _flag_refund(db: Session, order: Order, actor: User, request: Request) -> None:
    """Money paid for an order that won't go ahead is owed back to the customer."""
    if order.paid_cents > 0:
        audit.record(db, "payment.refund_due", actor_id=actor.id, entity_type="order",
                     entity_id=order.id,
                     details={"order_number": order.order_number,
                              "amount_cents": order.paid_cents},
                     request=request)


# ---------- Weighing (final price of per-kg items) ----------

WEIGHABLE = {OrderStatus.RECEIVED, OrderStatus.PROCESSING}


def weigh(db: Session, order: Order, staff_user: User, actual: dict, request: Request) -> None:
    """Records the real weight of every per-kg line. The original lines stay
    frozen; the difference is stored as adjustments (SEC-042). If the price
    goes up the customer must pay the balance before the order can be marked
    ready; if it goes down, a refund is owed."""
    if not order.is_estimate:
        raise _conflict("This order has no per-kg items left to weigh")
    if order.status not in WEIGHABLE:
        raise _conflict("Weigh the laundry after receiving it; the order is "
                        + _label(order.status))
    per_kg = {i.service_id: i for i in order.items if i.pricing_unit == PricingUnit.PER_KG}
    if set(actual) != set(per_kg):
        raise _invalid("Give the actual weight of every per-kg item, and only those")

    total = 0
    changes = []
    for service_id, item in per_kg.items():
        qty = actual[service_id]
        delta = (qty - item.quantity) * item.unit_price_cents
        total += delta
        db.add(OrderAdjustment(order_id=order.id, order_item_id=item.id,
                               estimated_quantity=item.quantity, actual_quantity=qty,
                               unit_price_cents=item.unit_price_cents, amount_cents=delta,
                               recorded_by_id=staff_user.id))
        changes.append({"service": item.service_name, "estimated": item.quantity,
                        "actual": qty, "amount_cents": delta})

    order.adjustment_cents += total
    order.is_estimate = False
    order.weighed_at = datetime.now(UTC)
    audit.record(db, "order.weighed", actor_id=staff_user.id, entity_type="order",
                 entity_id=order.id,
                 details={"order_number": order.order_number, "lines": changes,
                          "adjustment_cents": total},
                 request=request)
    if order.balance_cents > 0:
        notifications.customer(
            db, order, "payment.balance_due", "Balance to pay",
            f"Your laundry for order {order.order_number} weighed more than estimated. "
            f"Please pay the balance of {format_rands(order.balance_cents)} so we can "
            "deliver it.")
    elif order.balance_cents < 0:
        notifications.customer(
            db, order, "payment.refund_due", "Refund on its way",
            "Your laundry weighed less than estimated. "
            f"{format_rands(-order.balance_cents)} will be refunded to you.")
        audit.record(db, "payment.refund_due", actor_id=staff_user.id, entity_type="order",
                     entity_id=order.id, details={"amount_cents": -order.balance_cents},
                     request=request)
    db.commit()
