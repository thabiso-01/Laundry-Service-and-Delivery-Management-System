"""Payments (URS 2.1 "make payments", SEC-042, Business Rule 11).

The customer is sent to the provider's checkout with an amount we computed.
The provider later calls our webhook; only a correctly signed notification
for the exact amount marks the payment paid. Every notification is stored
(append-only) whatever its outcome, and duplicates are harmless.

Provider adapters
-----------------
"sandbox" – simulates a gateway for development and demos. Notifications are
            signed with HMAC-SHA256 over "reference|provider_id|status|amount".
A real South African provider (PayFast, Yoco, Ozow, Peach) needs a merchant
account; add its signature check and checkout fields alongside `_sign`.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Order, Payment, PaymentEvent, User
from app.models.enums import OrderStatus, PaymentStatus
from app.services import audit, notifications
from app.schemas.business import format_rands

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
NOT_PAYABLE = {OrderStatus.CANCELLED, OrderStatus.DECLINED}


def _secret() -> bytes:
    if settings.payment_webhook_secret:
        return settings.payment_webhook_secret.encode()
    return hashlib.sha256(b"laundryconnect:payments:" + settings.jwt_secret_key.encode()).digest()


def sign(reference: str, provider_payment_id: str, status_: str, amount_cents: int) -> str:
    message = f"{reference}|{provider_payment_id}|{status_}|{amount_cents}".encode()
    return hmac.new(_secret(), message, hashlib.sha256).hexdigest()


def _reference(db: Session) -> str:
    while True:
        ref = "PAY-" + "".join(secrets.choice(_ALPHABET) for _ in range(12))
        if not db.scalar(select(Payment.id).where(Payment.reference == ref)):
            return ref


# ---------- Checkout ----------

def checkout(db: Session, order: Order, customer: User, request: Request) -> Payment:
    """Starts (or reuses) a checkout for whatever the customer currently owes."""
    if order.status in NOT_PAYABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, "This order can no longer be paid")
    due = order.balance_cents
    if due <= 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing is owed on this order")

    pending = db.scalars(select(Payment).where(Payment.order_id == order.id,
                                               Payment.status == PaymentStatus.PENDING)).all()
    for p in pending:
        if p.amount_cents == due:
            return p  # same amount: reuse, so double-clicking "Pay" is harmless
        p.status = PaymentStatus.CANCELLED  # amount changed (e.g. after weighing)

    payment = Payment(order_id=order.id, reference=_reference(db),
                      provider=settings.payment_provider, amount_cents=due)
    db.add(payment)
    db.flush()
    audit.record(db, "payment.started", actor_id=customer.id, entity_type="payment",
                 entity_id=payment.id,
                 details={"order_number": order.order_number, "amount_cents": due,
                          "reference": payment.reference},
                 request=request)
    db.commit()
    return payment


def checkout_details(payment: Payment, order: Order, customer: User) -> dict[str, Any]:
    """What the frontend needs to send the customer to the provider."""
    details: dict[str, Any] = {
        "provider": payment.provider,
        "reference": payment.reference,
        "amount_cents": payment.amount_cents,
        "amount_display": format_rands(payment.amount_cents),
        "form_action": None,
        "form_fields": None,
    }
    if payment.provider == "payfast":
        from app.services import payfast  # imports this module too
        form = payfast.checkout_form(payment, order, customer)
        # The browser must POST these fields, in this order, to form_action
        details.update(checkout_url=form["action"], form_action=form["action"],
                       form_fields=form["fields"])
    else:
        # Sandbox: the app calls this to simulate the gateway's result
        details["checkout_url"] = f"/api/payments/sandbox/{payment.reference}/complete"
    return details


# ---------- Provider notification (webhook) ----------

def _event(db: Session, payment: Payment | None, payload: dict, outcome: str,
           valid: bool) -> None:
    db.add(PaymentEvent(payment_id=payment.id if payment else None,
                        reference=str(payload.get("reference"))[:100], outcome=outcome,
                        signature_valid=valid, payload=payload))


def handle_notification(db: Session, payload: dict, request: Request | None) -> str:
    """Processes a provider notification. Returns the outcome; the webhook
    always answers 200 so the provider doesn't retry forever, except for a
    bad signature."""
    reference = str(payload.get("reference", ""))
    provider_id = str(payload.get("provider_payment_id", ""))
    status_ = str(payload.get("status", ""))
    try:
        amount = int(payload.get("amount_cents"))
    except (TypeError, ValueError):
        amount = -1
    expected = sign(reference, provider_id, status_, amount)
    valid = hmac.compare_digest(str(payload.get("signature", "")), expected)

    payment = db.scalar(select(Payment).where(Payment.reference == reference)
                        .with_for_update())
    if not valid:
        _event(db, payment, payload, "bad_signature", False)
        audit.record(db, "payment.bad_signature", details={"reference": reference},
                     request=request)
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid signature")

    return apply_verified(db, payment, provider_id, status_, amount, payload, request)


def apply_verified(db: Session, payment: Payment | None, provider_id: str, status_: str,
                   amount: int, payload: dict, request: Request | None) -> str:
    """Applies a notification whose authenticity has already been checked, for
    any provider. status_ is one of: paid, failed, cancelled."""
    if payment is None:
        outcome = "unknown_reference"
    elif payment.status == PaymentStatus.PAID:
        outcome = "duplicate"
    elif amount != payment.amount_cents:
        # SEC-042: a notification for any other amount is never accepted
        outcome = "amount_mismatch"
        audit.record(db, "payment.amount_mismatch", entity_type="payment",
                     entity_id=payment.id,
                     details={"expected": payment.amount_cents, "received": amount},
                     request=request)
    elif status_ == "paid":
        outcome = "applied"
        _mark_paid(db, payment, provider_id, request)
    elif status_ == "failed":
        outcome = "failed"
        payment.status = PaymentStatus.FAILED
        payment.provider_payment_id = provider_id
        order = db.get(Order, payment.order_id)
        notifications.customer(db, order, "payment.failed", "Payment didn't go through",
                               f"Your payment for order {order.order_number} failed. "
                               "You can try again from the order page.")
    elif status_ == "cancelled":
        # The customer backed out on the provider's page
        outcome = "cancelled"
        if payment.status == PaymentStatus.PENDING:
            payment.status = PaymentStatus.CANCELLED
            payment.provider_payment_id = provider_id
    else:
        outcome = "ignored_status"

    _event(db, payment, payload, outcome, True)
    db.commit()
    return outcome


def _mark_paid(db: Session, payment: Payment, provider_id: str, request: Request | None) -> None:
    order = db.get(Order, payment.order_id, with_for_update=True)
    first_payment = order.paid_cents == 0
    payment.status = PaymentStatus.PAID
    payment.provider_payment_id = provider_id
    payment.paid_at = datetime.now(UTC)
    order.paid_cents += payment.amount_cents
    audit.record(db, "payment.received", entity_type="payment", entity_id=payment.id,
                 details={"order_number": order.order_number,
                          "amount_cents": payment.amount_cents,
                          "paid_cents": order.paid_cents},
                 request=request)
    notifications.customer(db, order, "payment.received", "Payment received",
                           f"We received {format_rands(payment.amount_cents)} for order "
                           f"{order.order_number}. Thank you!")
    if first_payment and order.status == OrderStatus.PLACED:
        notifications.notify(db, notifications.business_team(db, order.business_id),
                             "order.new", "New order",
                             f"Order {order.order_number} is paid and waiting for you to "
                             "accept it.", order=order)
    if order.status in NOT_PAYABLE:
        # Paid after it was cancelled (race) – flag it so the money goes back
        audit.record(db, "payment.refund_due", entity_type="order", entity_id=order.id,
                     details={"amount_cents": payment.amount_cents}, request=request)
