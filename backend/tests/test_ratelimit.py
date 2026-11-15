"""Per-IP rate limits (SEC-038, SEC-040)."""

import pytest
from sqlalchemy import select

from app.config import settings
from app.core.ratelimit import Limiter
from app.models import AuditLog
from app.models.enums import UserRole
from tests.conftest import PASSWORD, auth_header


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


# ---------- The limiter itself ----------

def test_sliding_window_and_retry_after():
    clock = Clock()
    lim = Limiter(clock)
    assert [lim.hit("k", 3, 60)[0] for _ in range(3)] == [True, True, True]
    allowed, retry, first = lim.hit("k", 3, 60)
    assert (allowed, first) == (False, True) and retry == pytest.approx(60)
    clock.now += 30
    allowed, retry, first = lim.hit("k", 3, 60)
    assert (allowed, first) == (False, False)  # still the same blocked window: log it once
    assert retry == pytest.approx(30)
    clock.now += 31  # the first hits have aged out
    assert lim.hit("k", 3, 60)[0] is True


def test_keys_are_independent():
    lim = Limiter(Clock())
    for _ in range(2):
        lim.hit("login:1.1.1.1", 2, 60)
    assert lim.hit("login:1.1.1.1", 2, 60)[0] is False
    assert lim.hit("login:2.2.2.2", 2, 60)[0] is True  # another IP isn't affected


# ---------- On the real endpoints ----------

def login(client, email, password="wrong-password"):
    return client.post("/api/auth/login", data={"username": email, "password": password})


def test_password_spraying_across_accounts_is_stopped(client, make_user, db, monkeypatch):
    """One network trying passwords on many different accounts (each account
    stays under its own lockout limit)."""
    monkeypatch.setattr(settings, "ratelimit_login_per_minute", 5)
    victims = [make_user(UserRole.CUSTOMER) for _ in range(6)]
    codes = [login(client, v.email).status_code for v in victims]
    assert codes == [401] * 5 + [429]

    blocked = login(client, victims[0].email, PASSWORD)  # even a correct password waits
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert "Too many requests" in blocked.json()["detail"]

    entries = db.scalars(select(AuditLog).where(AuditLog.action == "ratelimit.blocked")).all()
    assert len(entries) == 1  # logged once per window, not on every attempt
    assert entries[0].details["rule"] == "login-minute"


def test_mass_registration_is_stopped(client, monkeypatch):
    monkeypatch.setattr(settings, "ratelimit_register_per_hour", 3)

    def register(i):
        return client.post("/api/auth/register/customer", json={
            "email": f"bot{i}@example.com", "password": "BotPassword#1", "full_name": f"Bot {i}",
            "accept_privacy_policy": True})

    assert [register(i).status_code for i in range(4)] == [201, 201, 201, 429]


def test_registration_limit_covers_every_role(client, monkeypatch):
    monkeypatch.setattr(settings, "ratelimit_register_per_hour", 1)
    client.post("/api/auth/register/customer", json={
        "email": "first@example.com", "password": "BotPassword#1", "full_name": "First",
        "accept_privacy_policy": True})
    r = client.post("/api/auth/register/driver", json={
        "email": "second@example.com", "password": "BotPassword#1", "full_name": "Second",
        "accept_privacy_policy": True, "id_number": "P1234567"})
    assert r.status_code == 429


def test_password_change_guessing_is_stopped(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "ratelimit_password_change_per_15_min", 2)
    user = make_user(UserRole.CUSTOMER)
    codes = [client.post("/api/auth/change-password", headers=auth_header(user),
                         json={"current_password": "guess", "new_password": "NewPassword#99"}
                         ).status_code for _ in range(3)]
    assert codes == [400, 400, 429]


def test_report_spam_is_stopped(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "ratelimit_reports_per_hour", 2)
    user = make_user(UserRole.CUSTOMER)

    def report():
        return client.post("/api/incidents", headers=auth_header(user), json={
            "category": "fraud", "description": "Suspicious phone call claiming to be you."})

    assert [report().status_code for _ in range(3)] == [201, 201, 429]


def test_normal_use_is_unaffected(client, make_user):
    user = make_user(UserRole.CUSTOMER)
    for _ in range(3):
        assert login(client, user.email, PASSWORD).status_code == 200


def test_can_be_switched_off(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "ratelimit_enabled", False)
    monkeypatch.setattr(settings, "ratelimit_login_per_minute", 1)
    user = make_user(UserRole.CUSTOMER)
    assert [login(client, user.email, PASSWORD).status_code for _ in range(3)] == [200] * 3
