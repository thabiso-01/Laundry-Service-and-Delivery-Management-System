"""One-time codes for collection and delivery (SEC-005 – SEC-008, UAT-007, UAT-011).

* separate codes for collection and for final delivery;
* single use, with an expiry, and locked after too many wrong guesses;
* the customer can generate a fresh code, which kills the old one;
* the 6 digits are derived (HMAC) from the row's random id with a server key –
  never stored – so a database leak doesn't reveal live codes.
"""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Order, OrderOtp, User
from app.models.enums import OtpPurpose
from app.services import audit


def _key() -> bytes:
    return hashlib.sha256(b"laundryconnect:otp:" + settings.jwt_secret_key.encode()).digest()


def code_for(otp: OrderOtp) -> str:
    mac = hmac.new(_key(), otp.id.bytes, hashlib.sha256).digest()
    return f"{int.from_bytes(mac[:8], 'big') % 1_000_000:06d}"


def _expiry(order: Order, purpose: OtpPurpose, now: datetime) -> datetime:
    window_end = (order.collection_window_end if purpose == OtpPurpose.COLLECTION
                  else order.delivery_window_end)
    grace = timedelta(hours=settings.otp_grace_hours)
    # A code made late (e.g. driver running behind) still gets a usable lifetime
    return max(window_end + grace, now + grace)


def active(db: Session, order: Order, purpose: OtpPurpose) -> OrderOtp | None:
    return db.scalar(select(OrderOtp).where(
        OrderOtp.order_id == order.id, OrderOtp.purpose == purpose,
        OrderOtp.used_at.is_(None), OrderOtp.revoked_at.is_(None),
    ))


def revoke(db: Session, order: Order, purpose: OtpPurpose | None = None) -> None:
    now = datetime.now(UTC)
    query = select(OrderOtp).where(OrderOtp.order_id == order.id, OrderOtp.used_at.is_(None),
                                   OrderOtp.revoked_at.is_(None))
    if purpose:
        query = query.where(OrderOtp.purpose == purpose)
    for otp in db.scalars(query):
        otp.revoked_at = now
    db.flush()


def issue(db: Session, order: Order, purpose: OtpPurpose) -> OrderOtp:
    """Creates a new code, revoking any live one for the same purpose."""
    revoke(db, order, purpose)
    now = datetime.now(UTC)
    otp = OrderOtp(order_id=order.id, purpose=purpose, expires_at=_expiry(order, purpose, now))
    db.add(otp)
    db.flush()
    return otp


def _reject(detail: str, code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(code, detail)


def verify(
    db: Session, order: Order, purpose: OtpPurpose, code: str, actor: User, request: Request
) -> OrderOtp:
    """Checks the code and marks it used. A wrong guess is counted (and saved)
    before the error is raised."""
    otp = active(db, order, purpose)
    if otp is None:
        raise _reject("There is no valid code for this order. Ask the customer to "
                      "generate a new one in the app", status.HTTP_409_CONFLICT)
    now = datetime.now(UTC)
    if otp.expires_at <= now:
        raise _reject("This code has expired. Ask the customer to generate a new one",
                      status.HTTP_409_CONFLICT)
    if otp.failed_attempts >= settings.otp_max_attempts:
        raise _reject("Too many wrong codes. Ask the customer to generate a new one",
                      status.HTTP_423_LOCKED)

    if not hmac.compare_digest(code.strip(), code_for(otp)):
        otp.failed_attempts += 1
        audit.record(db, "otp.failed", actor_id=actor.id, entity_type="order",
                     entity_id=order.id,
                     details={"purpose": purpose.value, "attempt": otp.failed_attempts},
                     request=request)
        db.commit()
        left = settings.otp_max_attempts - otp.failed_attempts
        raise _reject(f"Wrong code. {left} attempt(s) left" if left > 0
                      else "Wrong code. This code is now locked",
                      status.HTTP_400_BAD_REQUEST if left > 0 else status.HTTP_423_LOCKED)

    otp.used_at = now  # SEC-008: can never be used again
    return otp
