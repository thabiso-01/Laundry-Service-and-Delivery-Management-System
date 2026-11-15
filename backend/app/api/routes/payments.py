"""Paying for orders (URS 2.1, SEC-042, Business Rule 11)."""

import secrets
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from app.api.deps import CustomerUser, DbSession
from app.api.routes.orders import _own_order
from app.config import settings
from app.models import Order, Payment
from app.schemas.engagement import CheckoutOut, PaymentOut, SandboxResultIn
from app.services import payfast, payments

router = APIRouter(tags=["payments"])


@router.post("/api/orders/{order_id}/pay", response_model=CheckoutOut)
def pay_order(order_id: uuid.UUID, customer: CustomerUser, db: DbSession,
              request: Request) -> CheckoutOut:
    """Start paying whatever you owe on the order (the order total, or the
    balance after weighing). Send the customer to `checkout_url`."""
    order = _own_order(db, customer, order_id, lock=True)
    payment = payments.checkout(db, order, customer, request)
    return CheckoutOut(payment_id=payment.id, **payments.checkout_details(payment, order, customer))


@router.post("/api/payments/payfast/notify")
async def payfast_notification(request: Request, db: DbSession) -> Response:
    """PayFast's ITN. Not for browsers: every notification is checked (signature,
    PayFast server address, PayFast confirmation, exact amount) before it counts."""
    if settings.payment_provider != "payfast":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    form = await request.form()
    pairs = [(k, v) for k, v in form.multi_items() if isinstance(v, str)]
    outcome = await run_in_threadpool(payfast.handle_itn, db, pairs, request)
    return Response(content=outcome, media_type="text/plain")  # 200 tells PayFast we've got it


@router.get("/api/orders/{order_id}/payments", response_model=list[PaymentOut])
def order_payments(order_id: uuid.UUID, customer: CustomerUser, db: DbSession) -> list[Payment]:
    order = _own_order(db, customer, order_id)
    return list(db.scalars(select(Payment).where(Payment.order_id == order.id)
                           .order_by(Payment.created_at)))


@router.post("/api/payments/notify")
def provider_notification(payload: Annotated[dict[str, Any], Body()], request: Request,
                          db: DbSession) -> dict:
    """Webhook the payment provider calls. Not for browsers: only a correctly
    signed notification for the exact amount marks a payment paid."""
    return {"outcome": payments.handle_notification(db, payload, request)}


@router.post("/api/payments/sandbox/{reference}/complete")
def sandbox_complete(reference: str, body: SandboxResultIn, customer: CustomerUser,
                     db: DbSession, request: Request) -> dict:
    """Development only: pretend to be the gateway finishing a checkout. Sends
    a properly signed notification through the same path a real one takes."""
    if settings.payment_provider != "sandbox":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    payment = db.scalar(select(Payment).where(Payment.reference == reference))
    order = db.get(Order, payment.order_id) if payment else None
    if payment is None or order is None or order.customer_id != customer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    provider_id = "SBX-" + secrets.token_hex(6).upper()
    payload = {"reference": reference, "provider_payment_id": provider_id,
               "status": body.outcome, "amount_cents": payment.amount_cents}
    payload["signature"] = payments.sign(reference, provider_id, body.outcome,
                                         payment.amount_cents)
    return {"outcome": payments.handle_notification(db, payload, request)}
