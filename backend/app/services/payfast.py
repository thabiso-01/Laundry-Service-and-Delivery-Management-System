"""PayFast payments (South Africa) – redirect checkout and ITN notifications.

Follows PayFast's official SDK (github.com/PayFast/payfast-php-sdk):

Checkout: the browser POSTs a signed form to https://{sandbox|www}.payfast.co.za/eng/process.
  signature = md5 of "key=value&..." over the fields in PayFast's documented
  attribute order, values trimmed and PHP-urlencoded (space → "+"), empty
  values left out, then "&passphrase=..." when a passphrase is set.

ITN (Instant Transaction Notification): PayFast POSTs the result to notify_url.
  Accepted only if ALL hold:
  1. signature over the posted fields (in posted order, up to "signature") is valid;
  2. the request comes from one of PayFast's servers – we check the connecting
     IP itself (the SDK only checks the Referer header, which is easy to fake);
  3. PayFast confirms the data: POST it back to /eng/query/validate → "VALID";
  4. the amount equals what we asked for, to the cent (SEC-042).
"""

import hashlib
import hmac
import socket
import time
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote_plus

import httpx
from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Order, Payment, PaymentEvent, User
from app.services import audit
from app.services import payments as payment_service

PAYFAST_HOSTS = ["www.payfast.co.za", "sandbox.payfast.co.za", "w1w.payfast.co.za", "w2w.payfast.co.za"]
STATUS_MAP = {"COMPLETE": "paid", "FAILED": "failed", "CANCELLED": "cancelled"}


def base_url() -> str:
    return "https://sandbox.payfast.co.za" if settings.payfast_sandbox else "https://www.payfast.co.za"


def _encode(value: Any) -> str:
    # PHP urlencode(): like quote_plus, but "~" is encoded too
    return quote_plus(str(value).strip(), safe="").replace("~", "%7E")


def param_string(pairs: list[tuple[str, Any]], passphrase: str | None) -> str:
    parts = [f"{k}={_encode(v)}" for k, v in pairs if str(v).strip() != ""]
    if passphrase:
        parts.append(f"passphrase={_encode(passphrase)}")
    return "&".join(parts)


def signature(pairs: list[tuple[str, Any]], passphrase: str | None) -> str:
    return hashlib.md5(param_string(pairs, passphrase).encode()).hexdigest()


def amount_text(cents: int) -> str:
    return f"{Decimal(cents) / 100:.2f}"


# ---------- Checkout ----------

def checkout_form(payment: Payment, order: Order, customer: User) -> dict[str, Any]:
    """The fields the browser posts to PayFast, already signed. Order matters."""
    if not (settings.payfast_merchant_id and settings.payfast_merchant_key):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Online payment isn't set up yet. Please try again later")
    pairs: list[tuple[str, Any]] = [
        ("merchant_id", settings.payfast_merchant_id),
        ("merchant_key", settings.payfast_merchant_key),
        ("return_url", f"{settings.public_app_url}/orders/{order.id}?payment=return"),
        ("cancel_url", f"{settings.public_app_url}/orders/{order.id}?payment=cancelled"),
        ("notify_url", f"{settings.public_api_url}/api/payments/payfast/notify"),
        # Only what PayFast needs to send a receipt (POPIA: minimum necessary)
        ("name_first", customer.full_name.split()[0] if customer.full_name else ""),
        ("email_address", customer.email),
        ("m_payment_id", payment.reference),
        ("amount", amount_text(payment.amount_cents)),
        ("item_name", f"LaundryConnect order {order.order_number}"[:100]),
    ]
    pairs = [(k, str(v).strip()) for k, v in pairs if str(v).strip() != ""]
    pairs.append(("signature", signature(pairs, settings.payfast_passphrase)))
    return {"action": f"{base_url()}/eng/process", "fields": pairs}


# ---------- Notification checks ----------

_ip_cache: tuple[float, set[str]] = (0.0, set())


def _resolve_hosts() -> set[str]:
    """IP addresses of PayFast's notification servers, cached for an hour."""
    global _ip_cache
    when, ips = _ip_cache
    if time.monotonic() - when < 3600 and ips:
        return ips
    found: set[str] = set()
    for host in PAYFAST_HOSTS:
        try:
            found.update(socket.gethostbyname_ex(host)[2])
        except OSError:
            continue
    _ip_cache = (time.monotonic(), found)
    return found


def _confirm_with_payfast(body: str) -> bool:
    response = httpx.post(f"{base_url()}/eng/query/validate", content=body,
                          headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=10)
    return response.text.strip() == "VALID"


def _cents(text_value: str) -> int | None:
    try:
        return int((Decimal(text_value) * 100).to_integral_value())
    except (InvalidOperation, TypeError):
        return None


def _reject(db: Session, payload: dict, outcome: str, request: Request,
            payment: Payment | None = None) -> HTTPException:
    db.add(PaymentEvent(payment_id=payment.id if payment else None,
                        reference=str(payload.get("m_payment_id"))[:100], outcome=outcome,
                        signature_valid=outcome != "bad_signature", payload=payload))
    audit.record(db, f"payment.payfast_{outcome}",
                 details={"reference": payload.get("m_payment_id"), "ip": request.client.host
                          if request.client else None}, request=request)
    db.commit()
    return HTTPException(status.HTTP_400_BAD_REQUEST, "Notification rejected")


def handle_itn(db: Session, pairs: list[tuple[str, str]], request: Request) -> str:
    payload = dict(pairs)

    # 1. Signature over the posted fields, in posted order, up to "signature"
    signed: list[tuple[str, str]] = []
    for key, value in pairs:
        if key == "signature":
            break
        signed.append((key, value))
    expected = signature(signed, settings.payfast_passphrase)
    if not hmac.compare_digest(payload.get("signature", ""), expected):
        raise _reject(db, payload, "bad_signature", request)

    # 2. From PayFast's servers
    ip = request.client.host if request.client else ""
    if settings.payfast_verify_source_ip and ip not in _resolve_hosts():
        raise _reject(db, payload, "bad_source", request)

    if payload.get("merchant_id") != settings.payfast_merchant_id:
        raise _reject(db, payload, "wrong_merchant", request)

    payment = db.scalar(select(Payment).where(Payment.reference == payload.get("m_payment_id"))
                        .with_for_update())

    # 3. PayFast confirms it sent this exact data
    if settings.payfast_server_confirmation:
        try:
            confirmed = _confirm_with_payfast(param_string(signed, settings.payfast_passphrase))
        except httpx.HTTPError:
            confirmed = False
        if not confirmed:
            raise _reject(db, payload, "not_confirmed", request, payment)

    # 4. Amount and status are then applied exactly like any other provider
    amount = _cents(payload.get("amount_gross", ""))
    outcome_status = STATUS_MAP.get(payload.get("payment_status", ""), "unknown")
    return payment_service.apply_verified(db, payment, payload.get("pf_payment_id", ""),
                                          outcome_status, amount if amount is not None else -1,
                                          payload, request)
