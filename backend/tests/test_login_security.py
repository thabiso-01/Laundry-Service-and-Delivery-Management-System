"""Login protection: lockout (SEC-040), new-device alerts (SEC-045) and
two-step login with an authenticator app (SEC-039)."""

import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core import mfa
from app.models import AuditLog, Notification
from app.models.enums import UserRole
from tests.conftest import PASSWORD, auth_header


@pytest.fixture
def user(make_user):
    return make_user(UserRole.CUSTOMER)


def login(client, user, password=PASSWORD, agent="Chrome on Android"):
    return client.post("/api/auth/login", data={"username": user.email, "password": password},
                       headers={"User-Agent": agent})


def kinds(db, user):
    return db.scalars(select(Notification.kind).where(Notification.user_id == user.id)).all()


# ---------- Lockout ----------

def test_account_locks_after_repeated_wrong_passwords(client, db, user):
    for _ in range(4):
        assert login(client, user, "wrong-password").status_code == 401
    assert login(client, user, "wrong-password").status_code == 401  # 5th: now locked
    r = login(client, user)  # even the right password is refused while locked
    assert r.status_code == 429
    assert "Try again in 15 minute(s)" in r.json()["detail"]
    assert "security.locked" in kinds(db, user)
    assert db.scalar(select(AuditLog).where(AuditLog.action == "auth.locked"))


def test_lock_expires(client, db, user):
    for _ in range(5):
        login(client, user, "wrong-password")
    user.locked_until = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()
    assert login(client, user).status_code == 200
    assert user.failed_login_count == 0


def test_success_resets_the_counter(client, user):
    for _ in range(4):
        login(client, user, "wrong-password")
    assert login(client, user).status_code == 200
    for _ in range(4):
        login(client, user, "wrong-password")
    assert login(client, user).status_code == 200  # not locked: counter restarted


# ---------- New-device alerts ----------

def test_new_device_triggers_alert(client, db, user):
    assert login(client, user, agent="Chrome on Android").status_code == 200
    assert "security.new_device" not in kinds(db, user)  # first ever sign-in: nothing to compare
    login(client, user, agent="Chrome on Android")
    assert "security.new_device" not in kinds(db, user)  # same device
    login(client, user, agent="Firefox on Windows")
    assert kinds(db, user).count("security.new_device") == 1


# ---------- Two-step login (MFA) ----------

def enable_mfa(client, user):
    h = auth_header(user)
    setup = client.post("/api/auth/mfa/setup", headers=h).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/LaundryConnect:")
    r = client.post("/api/auth/mfa/enable", headers=h,
                    json={"code": mfa.code_for(setup["secret"])})
    assert r.status_code == 200, r.text
    return setup["secret"], r.json()["recovery_codes"]


def next_code(secret):
    # The current step was used to enable MFA; replay protection needs a newer one
    return mfa.code_for(secret, time.time() + mfa.STEP_SECONDS)


def test_mfa_login_flow(client, db, user):
    secret, recovery = enable_mfa(client, user)
    assert len(recovery) == 8
    assert client.get("/api/auth/me", headers=auth_header(user)).json()["mfa_enabled"] is True

    first = login(client, user).json()
    assert first["mfa_required"] is True and first["access_token"] is None

    # The half-way token is not a login token
    assert client.get("/api/auth/me",
                      headers={"Authorization": f"Bearer {first['mfa_token']}"}).status_code == 401

    r = client.post("/api/auth/login/mfa",
                    json={"mfa_token": first["mfa_token"], "code": next_code(secret)})
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200


def test_mfa_code_cannot_be_replayed(client, user):
    secret, _ = enable_mfa(client, user)
    code = next_code(secret)
    token = login(client, user).json()["mfa_token"]
    assert client.post("/api/auth/login/mfa",
                       json={"mfa_token": token, "code": code}).status_code == 200
    token = login(client, user).json()["mfa_token"]
    assert client.post("/api/auth/login/mfa",
                       json={"mfa_token": token, "code": code}).status_code == 401


def test_recovery_code_works_once(client, user):
    _, recovery = enable_mfa(client, user)
    token = login(client, user).json()["mfa_token"]
    assert client.post("/api/auth/login/mfa",
                       json={"mfa_token": token, "code": recovery[0]}).status_code == 200
    token = login(client, user).json()["mfa_token"]
    assert client.post("/api/auth/login/mfa",
                       json={"mfa_token": token, "code": recovery[0]}).status_code == 401


def test_wrong_mfa_codes_count_towards_lockout(client, user):
    enable_mfa(client, user)
    token = login(client, user).json()["mfa_token"]
    for _ in range(5):
        client.post("/api/auth/login/mfa", json={"mfa_token": token, "code": "000000"})
    assert login(client, user).status_code == 429


def test_secrets_are_not_stored_in_plain_text(client, db, user):
    secret, recovery = enable_mfa(client, user)
    assert secret not in (user.mfa_secret_encrypted or "")
    assert not set(recovery) & set(user.mfa_recovery_hashes)


def test_disable_needs_password_and_code(client, db, user):
    secret, _ = enable_mfa(client, user)
    h = auth_header(user)
    assert client.post("/api/auth/mfa/disable", headers=h,
                       json={"password": "wrong-password", "code": next_code(secret)}
                       ).status_code == 400
    r = client.post("/api/auth/mfa/disable", headers=h,
                    json={"password": PASSWORD, "code": next_code(secret)})
    assert r.status_code == 200
    assert login(client, user).json()["access_token"]  # back to one step
    assert "security.mfa_disabled" in kinds(db, user)


def test_cannot_enable_twice(client, user):
    enable_mfa(client, user)
    assert client.post("/api/auth/mfa/setup", headers=auth_header(user)).status_code == 409
