from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, BusinessStaff, User
from app.models.enums import AccountStatus, UserRole
from tests.conftest import PASSWORD, auth_header

VALID_SA_ID = "8001015009087"  # passes the Luhn checksum


def customer_payload(**overrides):
    data = {
        "email": "Thandi@Example.co.za",
        "password": PASSWORD,
        "full_name": "Thandi Mokoena",
        "phone": "082 123 4567",
        "accept_privacy_policy": True,
    }
    return data | overrides


def login(client, email, password=PASSWORD):
    return client.post("/api/auth/login", data={"username": email, "password": password})


# ---------- Registration ----------

def test_customer_can_register_login_and_see_profile(client, db):
    r = client.post("/api/auth/register/customer", json=customer_payload())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "thandi@example.co.za"  # lower-cased
    assert body["phone"] == "+27821234567"  # normalised
    assert body["role"] == "customer"
    assert PASSWORD not in r.text and "password_hash" not in r.text and "$argon2" not in r.text

    user = db.scalar(select(User).where(User.email == "thandi@example.co.za"))
    assert user.password_hash.startswith("$argon2")
    assert user.customer_profile is not None
    assert user.privacy_consent_at is not None

    r = login(client, "THANDI@example.co.za")
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["role"] == "customer"


def test_duplicate_email_is_rejected_case_insensitively(client):
    assert client.post("/api/auth/register/customer", json=customer_payload()).status_code == 201
    r = client.post("/api/auth/register/customer",
                    json=customer_payload(email="THANDI@example.co.za", phone=None))
    assert r.status_code == 409
    assert "email" in r.json()["detail"]


def test_duplicate_phone_is_rejected(client):
    assert client.post("/api/auth/register/customer", json=customer_payload()).status_code == 201
    r = client.post("/api/auth/register/customer",
                    json=customer_payload(email="other@example.co.za", phone="+27821234567"))
    assert r.status_code == 409
    assert "phone" in r.json()["detail"]


def test_registration_requires_privacy_consent(client):
    r = client.post("/api/auth/register/customer",
                    json=customer_payload(accept_privacy_policy=False))
    assert r.status_code == 422


def test_short_password_rejected(client):
    r = client.post("/api/auth/register/customer", json=customer_payload(password="short"))
    assert r.status_code == 422


def test_invalid_phone_rejected(client):
    r = client.post("/api/auth/register/customer", json=customer_payload(phone="12345"))
    assert r.status_code == 422


def test_driver_registers_as_pending(client):
    r = client.post("/api/auth/register/driver", json=customer_payload(
        email="sipho@example.co.za", id_number=VALID_SA_ID, vehicle_type="motorcycle"))
    assert r.status_code == 201, r.text

    token = login(client, "sipho@example.co.za").json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["role"] == "driver"
    assert me["driver"] == {
        "verification_status": "pending", "rejection_reason": None, "is_available": False,
    }


def test_driver_with_invalid_sa_id_rejected(client):
    r = client.post("/api/auth/register/driver", json=customer_payload(
        email="sipho@example.co.za", id_number="8001015009088"))  # bad checksum
    assert r.status_code == 422


def test_driver_duplicate_id_number_rejected(client):
    p = customer_payload(email="a@example.co.za", phone=None, id_number=VALID_SA_ID)
    assert client.post("/api/auth/register/driver", json=p).status_code == 201
    p = customer_payload(email="b@example.co.za", phone=None, id_number=VALID_SA_ID)
    assert client.post("/api/auth/register/driver", json=p).status_code == 409


def test_business_registration_creates_pending_business_with_owner(client, db):
    r = client.post("/api/auth/register/business", json=customer_payload(
        email="owner@sparkle.co.za",
        business_name="Sparkle Laundry",
        registration_number="2020/123456/07",
        address={"city": "Pretoria", "latitude": -25.75, "longitude": 28.19},
    ))
    assert r.status_code == 201, r.text

    user = db.scalar(select(User).where(User.email == "owner@sparkle.co.za"))
    membership = db.scalar(select(BusinessStaff).where(BusinessStaff.user_id == user.id))
    assert membership.staff_role.value == "owner"
    assert membership.business.verification_status.value == "pending"
    assert membership.business.city == "Pretoria"

    token = login(client, "owner@sparkle.co.za").json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert me["business"]["business_name"] == "Sparkle Laundry"
    assert me["business"]["staff_role"] == "owner"


def test_there_is_no_public_admin_registration(client):
    r = client.post("/api/auth/register/admin", json=customer_payload())
    assert r.status_code in (404, 405)


def test_role_cannot_be_injected_into_registration(client):
    r = client.post("/api/auth/register/customer", json=customer_payload(role="admin"))
    assert r.status_code == 201
    assert r.json()["role"] == "customer"


# ---------- Login ----------

def test_wrong_password_and_unknown_email_give_same_error(client, make_user, db):
    user = make_user(UserRole.CUSTOMER)
    wrong_pw = login(client, user.email, "not-the-password")
    unknown = login(client, "nobody@example.co.za")
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()

    actions = db.scalars(select(AuditLog.action)).all()
    assert actions.count("auth.login_failed") == 2


def test_successful_login_is_audited(client, make_user, db):
    user = make_user(UserRole.CUSTOMER)
    assert login(client, user.email).status_code == 200
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "auth.login"))
    assert entry.actor_user_id == user.id
    assert user.last_login_at is not None


def test_suspended_user_cannot_log_in_or_use_old_token(client, make_user, db):
    user = make_user(UserRole.CUSTOMER)
    headers = auth_header(user)  # token issued before suspension
    user.status = AccountStatus.SUSPENDED
    db.flush()

    assert login(client, user.email).status_code == 403
    assert client.get("/api/auth/me", headers=headers).status_code == 403


# ---------- Tokens ----------

def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_tampered_token_rejected(client, make_user):
    user = make_user(UserRole.CUSTOMER)
    token = auth_header(user)["Authorization"] + "x"
    assert client.get("/api/auth/me", headers={"Authorization": token}).status_code == 401


def test_expired_token_rejected(client, make_user):
    user = make_user(UserRole.CUSTOMER)
    past = datetime.now(UTC) - timedelta(hours=2)
    token = jwt.encode(
        {"sub": str(user.id), "type": "access", "iat": past, "exp": past + timedelta(minutes=30)},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm,
    )
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_token_signed_with_other_key_rejected(client, make_user):
    user = make_user(UserRole.ADMIN)
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(user.id), "type": "access", "iat": now, "exp": now + timedelta(minutes=5)},
        "attacker-chosen-secret-that-is-long-enough", algorithm="HS256",
    )
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
