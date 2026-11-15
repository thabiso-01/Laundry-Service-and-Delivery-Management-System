"""SMS delivery for important notifications (UR-016, SEC-045).

Outbox pattern: notifications.notify() marks qualifying messages
sms_status="pending" inside the same transaction as the event; a background
worker sends them only after that transaction has committed, so a rolled-back
action never texts anyone. Failed sends are retried, then recorded.

Providers
---------
log      development: writes the SMS to the server log, nothing is sent
bulksms  BulkSMS JSON API v1 (https://www.bulksms.com/developer/json/v1/):
         POST https://api.bulksms.com/v1/messages, HTTP Basic with an API token,
         body [{"to": "+27…", "body": "…"}], 201 Created on success;
         deduplication-id makes retries safe.
"""

import logging
import threading
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Notification, User

log = logging.getLogger("laundryconnect.sms")

# Only time-critical or security messages cost an SMS; the rest stay in-app
SMS_KINDS = {
    "driver.assigned", "order.out_for_delivery", "order.delivered", "order.declined",
    "payment.balance_due", "security.locked", "security.new_device", "security.mfa_disabled",
}
MAX_CHARS = 306  # two SMS segments


class SmsError(Exception):
    pass


def text_for(n: Notification) -> str:
    message = f"LaundryConnect: {n.title}. {n.body}"
    # Plain "..." – one non-GSM character would switch the whole SMS to Unicode
    # and roughly halve how much text each paid segment can carry
    return message if len(message) <= MAX_CHARS else message[:MAX_CHARS - 3] + "..."


def _send_log(to: str, text: str, dedup: int) -> str:
    log.info("SMS (log only) to %s: %s", to, text)
    return f"log-{dedup}"


def _send_bulksms(to: str, text: str, dedup: int) -> str:
    if not (settings.bulksms_token_id and settings.bulksms_token_secret):
        raise SmsError("BulkSMS API token isn't configured")
    try:
        response = httpx.post(
            "https://api.bulksms.com/v1/messages",
            params={"auto-unicode": "true", "deduplication-id": dedup},
            json=[{"to": to, "body": text}],
            auth=(settings.bulksms_token_id, settings.bulksms_token_secret),
            timeout=15,
        )
    except httpx.HTTPError as e:
        raise SmsError(f"Couldn't reach BulkSMS: {e}") from e
    if response.status_code != 201:
        try:
            detail = response.json().get("title") or response.text
        except ValueError:
            detail = response.text
        raise SmsError(f"BulkSMS {response.status_code}: {str(detail)[:200]}")
    created = response.json()
    return str(created[0].get("id")) if created else "unknown"


PROVIDERS = {"log": _send_log, "bulksms": _send_bulksms}


def send(to: str, text: str, dedup: int) -> str:
    provider = PROVIDERS.get(settings.sms_provider)
    if provider is None:
        raise SmsError(f"Unknown SMS_PROVIDER {settings.sms_provider!r}")
    return provider(to, text, dedup)


def deliver_pending(db: Session, limit: int = 50) -> dict[str, int]:
    """Sends queued SMS. Safe to run in several processes (rows are locked)."""
    counts = {"sent": 0, "failed": 0, "skipped": 0, "retry": 0}
    day_ago = datetime.now(UTC) - timedelta(hours=24)
    queued = db.scalars(
        select(Notification)
        .where(Notification.sms_status == "pending", Notification.created_at >= day_ago)
        .order_by(Notification.created_at).limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for n in queued:
        user = db.get(User, n.user_id)
        if not user or not user.phone or not user.sms_enabled:
            n.sms_status, n.sms_error = "skipped", "no phone or SMS switched off"
            counts["skipped"] += 1
            continue
        sent_today = db.scalar(select(func.count()).select_from(Notification).where(
            Notification.user_id == user.id, Notification.sms_status == "sent",
            Notification.sms_sent_at >= day_ago))
        if sent_today >= settings.sms_max_per_user_per_day:
            n.sms_status, n.sms_error = "skipped", "daily SMS limit reached"
            counts["skipped"] += 1
            continue
        n.sms_attempts += 1
        try:
            # Same id on every retry: BulkSMS won't send the same message twice
            n.sms_provider_id = send(user.phone, text_for(n), n.id.int % 2**31)
            n.sms_status, n.sms_sent_at, n.sms_error = "sent", datetime.now(UTC), None
            counts["sent"] += 1
        except SmsError as e:
            n.sms_error = str(e)[:300]
            if n.sms_attempts >= settings.sms_max_attempts:
                n.sms_status = "failed"
                counts["failed"] += 1
                log.warning("SMS %s failed for good: %s", n.id, e)
            else:
                counts["retry"] += 1
        db.commit()
    db.commit()
    return counts


# ---------- Background worker ----------

_stop = threading.Event()
_thread: threading.Thread | None = None


def _loop() -> None:
    from app.database import SessionLocal
    while not _stop.wait(settings.sms_poll_seconds):
        try:
            with SessionLocal() as db:
                deliver_pending(db)
        except Exception:  # never let one bad cycle kill the worker
            log.exception("SMS worker cycle failed")


def start_worker() -> None:
    global _thread
    if not settings.sms_worker_enabled or (_thread and _thread.is_alive()):
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="sms-worker", daemon=True)
    _thread.start()


def stop_worker() -> None:
    _stop.set()
