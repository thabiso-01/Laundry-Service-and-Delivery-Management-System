"""SMS for important notifications (UR-016, SEC-045). BulkSMS is never called."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.models import Notification
from app.models.enums import UserRole
from app.services import notifications, sms
from tests.conftest import auth_header


@pytest.fixture
def phone_user(make_user):
    return make_user(UserRole.CUSTOMER, phone="+27821234567")


@pytest.fixture
def outbox(monkeypatch):
    """Capture what would be sent."""
    sent = []

    def fake(to, text, dedup):
        sent.append({"to": to, "text": text, "dedup": dedup})
        return f"msg-{len(sent)}"

    monkeypatch.setitem(sms.PROVIDERS, "log", fake)
    return sent


def queued(db, user):
    return db.scalars(select(Notification).where(Notification.user_id == user.id)
                      .order_by(Notification.created_at)).all()


# ---------- What gets queued ----------

def test_important_messages_are_queued_for_sms(db, phone_user):
    notifications.notify(db, [phone_user], "order.out_for_delivery", "Out for delivery", "On its way.")
    notifications.notify(db, [phone_user], "order.collected", "Collected", "Collected.")  # in-app only
    db.flush()
    statuses = [n.sms_status for n in queued(db, phone_user)]
    assert statuses == ["pending", None]


def test_no_phone_or_opted_out_means_no_sms(db, make_user, phone_user):
    no_phone = make_user(UserRole.CUSTOMER)
    phone_user.sms_enabled = False
    notifications.notify(db, [no_phone, phone_user], "order.delivered", "Delivered", "Done.")
    db.flush()
    assert queued(db, no_phone)[0].sms_status is None
    assert queued(db, phone_user)[0].sms_status is None
    assert queued(db, phone_user)[0].title == "Delivered"  # still in the inbox


# ---------- Sending ----------

def test_pending_sms_are_sent(db, phone_user, outbox):
    notifications.notify(db, [phone_user], "driver.assigned", "Driver on the way", "Sipho will collect.")
    db.flush()
    assert sms.deliver_pending(db) == {"sent": 1, "failed": 0, "skipped": 0, "retry": 0}
    assert outbox == [{"to": "+27821234567",
                       "text": "LaundryConnect: Driver on the way. Sipho will collect.",
                       "dedup": outbox[0]["dedup"]}]
    n = queued(db, phone_user)[0]
    assert (n.sms_status, n.sms_provider_id) == ("sent", "msg-1")
    assert sms.deliver_pending(db)["sent"] == 0  # never sent twice


def test_long_messages_fit_two_segments(db, phone_user, outbox):
    notifications.notify(db, [phone_user], "order.declined", "Order declined", "x" * 500)
    db.flush()
    sms.deliver_pending(db)
    assert len(outbox[0]["text"]) == sms.MAX_CHARS
    assert outbox[0]["text"].endswith("...") and outbox[0]["text"].isascii()


def test_failures_are_retried_then_given_up(db, phone_user, monkeypatch):
    attempts = []

    def down(to, text, dedup):
        attempts.append(dedup)
        raise sms.SmsError("BulkSMS 403: Insufficient Credits")

    monkeypatch.setitem(sms.PROVIDERS, "log", down)
    notifications.notify(db, [phone_user], "security.locked", "Sign-in locked", "Too many tries.")
    db.flush()
    results = [sms.deliver_pending(db) for _ in range(4)]
    assert [r["retry"] for r in results[:2]] == [1, 1] and results[2]["failed"] == 1
    assert results[3] == {"sent": 0, "failed": 0, "skipped": 0, "retry": 0}
    n = queued(db, phone_user)[0]
    assert (n.sms_status, n.sms_attempts) == ("failed", 3)
    assert "Insufficient Credits" in n.sms_error
    assert len(set(attempts)) == 1  # same deduplication id on every retry


def test_daily_cap_protects_the_bill(db, phone_user, outbox, monkeypatch):
    monkeypatch.setattr(settings, "sms_max_per_user_per_day", 2)
    for i in range(3):
        notifications.notify(db, [phone_user], "order.delivered", f"Delivered {i}", "Done.")
    db.flush()
    result = sms.deliver_pending(db)
    assert (result["sent"], result["skipped"]) == (2, 1)
    assert queued(db, phone_user)[2].sms_error == "daily SMS limit reached"


def test_switching_off_after_queueing_still_stops_it(db, phone_user, outbox):
    notifications.notify(db, [phone_user], "order.delivered", "Delivered", "Done.")
    db.flush()
    phone_user.sms_enabled = False
    assert sms.deliver_pending(db)["skipped"] == 1
    assert outbox == []


def test_stale_messages_are_not_sent(db, phone_user, outbox):
    notifications.notify(db, [phone_user], "order.out_for_delivery", "Out for delivery", "Soon.")
    db.flush()
    queued(db, phone_user)[0].created_at = datetime.now(UTC) - timedelta(days=2)
    db.flush()
    assert sms.deliver_pending(db)["sent"] == 0 and outbox == []


# ---------- BulkSMS request format ----------

def test_bulksms_request(monkeypatch):
    monkeypatch.setattr(settings, "sms_provider", "bulksms")
    monkeypatch.setattr(settings, "bulksms_token_id", "TOKEN-ID")
    monkeypatch.setattr(settings, "bulksms_token_secret", "TOKEN-SECRET")
    calls = []

    def fake_post(url, params, json, auth, timeout):
        calls.append((url, params, json, auth))
        return httpx.Response(201, json=[{"id": "4711", "status": {"type": "ACCEPTED"}}])

    monkeypatch.setattr(sms.httpx, "post", fake_post)
    assert sms.send("+27821234567", "Hello", 42) == "4711"
    url, params, body, auth = calls[0]
    assert url == "https://api.bulksms.com/v1/messages"
    assert params == {"auto-unicode": "true", "deduplication-id": 42}
    assert body == [{"to": "+27821234567", "body": "Hello"}]
    assert auth == ("TOKEN-ID", "TOKEN-SECRET")


def test_bulksms_errors_are_reported(monkeypatch):
    monkeypatch.setattr(settings, "sms_provider", "bulksms")
    monkeypatch.setattr(settings, "bulksms_token_id", "id")
    monkeypatch.setattr(settings, "bulksms_token_secret", "secret")
    monkeypatch.setattr(sms.httpx, "post", lambda *a, **k: httpx.Response(
        403, json={"type": "https://developer.bulksms.com/json/v1/errors#insufficient-credits",
                   "title": "Insufficient Credits", "status": 403}))
    with pytest.raises(sms.SmsError, match="403: Insufficient Credits"):
        sms.send("+27821234567", "Hello", 1)


def test_bulksms_without_token_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "sms_provider", "bulksms")
    monkeypatch.setattr(settings, "bulksms_token_id", "")
    with pytest.raises(sms.SmsError, match="isn't configured"):
        sms.send("+27821234567", "Hello", 1)


# ---------- User preference ----------

def test_user_can_switch_sms_off(client, phone_user):
    h = auth_header(phone_user)
    assert client.get("/api/auth/me", headers=h).json()["sms_enabled"] is True
    r = client.patch("/api/me/preferences", headers=h, json={"sms_enabled": False})
    assert r.json() == {"sms_enabled": False}
    assert client.get("/api/auth/me", headers=h).json()["sms_enabled"] is False
