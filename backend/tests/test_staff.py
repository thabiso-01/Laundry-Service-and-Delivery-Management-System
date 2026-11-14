"""Business staff management and first-login password change (SEC-011, SEC-017, SEC-038)."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, BusinessStaff, User
from app.models.enums import AccountStatus, BusinessStaffRole as S, UserRole
from app.models.enums import VerificationStatus as V
from tests.conftest import PASSWORD, auth_header

NEW_PASSWORD = "MyOwnSecret#2026"


@pytest.fixture
def biz(make_business):
    return make_business(V.APPROVED)


def add(client, actor, role="attendant", email="lerato@sparkle.co.za", **extra):
    return client.post("/api/business/staff", headers=auth_header(actor), json={
        "full_name": "Lerato Dlamini", "email": email, "staff_role": role, **extra,
    })


def login(client, email, password):
    return client.post("/api/auth/login", data={"username": email, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ---------- Adding staff ----------

def test_owner_adds_attendant_with_temporary_password(client, biz, db):
    r = add(client, biz.owner, phone="072 555 1234")
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["temporary_password"]) == 12
    assert body["staff_role"] == "attendant"
    assert body["must_change_password"] is True
    assert body["added_by_name"] == biz.owner.full_name
    assert body["phone"] == "+27725551234"

    user = db.get(User, body["user_id"])
    assert user.role == UserRole.BUSINESS
    assert user.privacy_consent_at is None
    assert body["temporary_password"] not in user.password_hash  # stored hashed

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "staff.added"))
    assert entry.actor_user_id == biz.owner.id
    assert entry.details["staff_role"] == "attendant"


def test_owner_can_add_manager(client, biz):
    assert add(client, biz.owner, role="manager").status_code == 201


def test_manager_can_add_attendant_but_not_manager(client, biz, add_staff):
    manager = add_staff(biz, S.MANAGER)
    assert add(client, manager, role="manager").status_code == 403
    assert add(client, manager, role="attendant").status_code == 201


def test_nobody_can_add_an_owner(client, biz):
    assert add(client, biz.owner, role="owner").status_code == 422


def test_attendant_cannot_manage_staff(client, biz, add_staff):
    attendant = add_staff(biz, S.ATTENDANT)
    assert add(client, attendant).status_code == 403
    assert client.get("/api/business/staff", headers=auth_header(attendant)).status_code == 403


def test_duplicate_email_rejected(client, biz):
    assert add(client, biz.owner).status_code == 201
    assert add(client, biz.owner, email="LERATO@sparkle.co.za").status_code == 409


def test_list_staff_owner_first(client, biz, add_staff):
    add_staff(biz, S.ATTENDANT)
    add_staff(biz, S.MANAGER)
    roles = [m["staff_role"] for m in
             client.get("/api/business/staff", headers=auth_header(biz.owner)).json()]
    assert roles == ["owner", "manager", "attendant"]


# ---------- First login ----------

def test_new_staff_must_change_password_before_working(client, biz):
    temp = add(client, biz.owner).json()["temporary_password"]

    r = login(client, "lerato@sparkle.co.za", temp)
    assert r.status_code == 200
    assert r.json()["must_change_password"] is True
    token = r.json()["access_token"]

    # Can see who they are, but nothing else
    me = client.get("/api/auth/me", headers=bearer(token))
    assert me.status_code == 200 and me.json()["must_change_password"] is True
    blocked = client.get("/api/business/services", headers=bearer(token))
    assert blocked.status_code == 403
    assert "temporary password" in blocked.json()["detail"]

    # Must accept the privacy policy themselves
    r = client.post("/api/auth/change-password", headers=bearer(token),
                    json={"current_password": temp, "new_password": NEW_PASSWORD})
    assert r.status_code == 422

    r = client.post("/api/auth/change-password", headers=bearer(token), json={
        "current_password": temp, "new_password": NEW_PASSWORD, "accept_privacy_policy": True,
    })
    assert r.status_code == 200, r.text
    new_token = r.json()["access_token"]
    assert client.get("/api/business/services", headers=bearer(new_token)).status_code == 200

    assert login(client, "lerato@sparkle.co.za", temp).status_code == 401
    assert login(client, "lerato@sparkle.co.za", NEW_PASSWORD).status_code == 200


def test_change_password_wrong_current_password(client, make_user, db):
    user = make_user(UserRole.CUSTOMER)
    r = client.post("/api/auth/change-password", headers=auth_header(user),
                    json={"current_password": "wrong-password", "new_password": NEW_PASSWORD})
    assert r.status_code == 400
    assert db.scalar(select(AuditLog).where(AuditLog.action == "auth.password_change_failed"))


def test_new_password_must_differ(client, make_user):
    user = make_user(UserRole.CUSTOMER)
    r = client.post("/api/auth/change-password", headers=auth_header(user),
                    json={"current_password": PASSWORD, "new_password": PASSWORD})
    assert r.status_code == 422


def test_changing_password_ends_older_sessions(client, make_user):
    user = make_user(UserRole.CUSTOMER)
    an_hour_ago = datetime.now(UTC) - timedelta(hours=1)
    old_token = jwt.encode(
        {"sub": str(user.id), "type": "access", "iat": an_hour_ago,
         "exp": an_hour_ago + timedelta(hours=2)},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm,
    )
    assert client.get("/api/auth/me", headers=bearer(old_token)).status_code == 200

    r = client.post("/api/auth/change-password", headers=auth_header(user),
                    json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert r.status_code == 200

    assert client.get("/api/auth/me", headers=bearer(old_token)).status_code == 401
    assert client.get("/api/auth/me", headers=bearer(r.json()["access_token"])).status_code == 200


# ---------- Changing access ----------

def _membership_id(db, user):
    return db.scalar(select(BusinessStaff.id).where(BusinessStaff.user_id == user.id))


def test_deactivating_staff_blocks_login_and_reactivating_restores(client, biz, add_staff, db):
    attendant = add_staff(biz, S.ATTENDANT)
    mid = _membership_id(db, attendant)
    h = auth_header(biz.owner)

    r = client.patch(f"/api/business/staff/{mid}", headers=h, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert attendant.status == AccountStatus.DEACTIVATED
    assert login(client, attendant.email, PASSWORD).status_code == 403

    client.patch(f"/api/business/staff/{mid}", headers=h, json={"is_active": True})
    assert attendant.status == AccountStatus.ACTIVE
    assert login(client, attendant.email, PASSWORD).status_code == 200


def test_reactivating_never_undoes_admin_suspension(client, biz, add_staff, db):
    attendant = add_staff(biz, S.ATTENDANT, active=False)
    attendant.status = AccountStatus.SUSPENDED  # an admin suspended them
    db.flush()
    mid = _membership_id(db, attendant)
    client.patch(f"/api/business/staff/{mid}", headers=auth_header(biz.owner),
                 json={"is_active": True})
    assert attendant.status == AccountStatus.SUSPENDED


def test_owner_promotes_attendant_and_change_is_audited(client, biz, add_staff, db):
    attendant = add_staff(biz, S.ATTENDANT)
    mid = _membership_id(db, attendant)
    r = client.patch(f"/api/business/staff/{mid}", headers=auth_header(biz.owner),
                     json={"staff_role": "manager"})
    assert r.status_code == 200 and r.json()["staff_role"] == "manager"
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "staff.updated"))
    assert entry.details == {"staff_role": {"from": "attendant", "to": "manager"}}


def test_manager_limits(client, biz, add_staff, db):
    manager = add_staff(biz, S.MANAGER)
    other_manager = add_staff(biz, S.MANAGER)
    attendant = add_staff(biz, S.ATTENDANT)
    h = auth_header(manager)

    # can't touch another manager, promote an attendant, or change themselves
    assert client.patch(f"/api/business/staff/{_membership_id(db, other_manager)}", headers=h,
                        json={"is_active": False}).status_code == 403
    assert client.patch(f"/api/business/staff/{_membership_id(db, attendant)}", headers=h,
                        json={"staff_role": "manager"}).status_code == 403
    assert client.patch(f"/api/business/staff/{_membership_id(db, manager)}", headers=h,
                        json={"is_active": False}).status_code == 403
    # but can deactivate an attendant
    assert client.patch(f"/api/business/staff/{_membership_id(db, attendant)}", headers=h,
                        json={"is_active": False}).status_code == 200


def test_owner_access_cannot_be_changed(client, biz, add_staff, db):
    owner_mid = _membership_id(db, biz.owner)
    r = client.patch(f"/api/business/staff/{owner_mid}", headers=auth_header(biz.owner),
                     json={"is_active": False})
    assert r.status_code == 403


def test_cannot_manage_another_businesses_staff(client, biz, make_business, add_staff, db):
    other = make_business(V.APPROVED)
    their_attendant = add_staff(other, S.ATTENDANT)
    mid = _membership_id(db, their_attendant)
    h = auth_header(biz.owner)
    assert client.patch(f"/api/business/staff/{mid}", headers=h,
                        json={"is_active": False}).status_code == 404
    assert client.post(f"/api/business/staff/{mid}/reset-password", headers=h).status_code == 404
    listed = {m["user_id"] for m in client.get("/api/business/staff", headers=h).json()}
    assert str(their_attendant.id) not in listed


def test_empty_update_rejected(client, biz, add_staff, db):
    mid = _membership_id(db, add_staff(biz, S.ATTENDANT))
    h = auth_header(biz.owner)
    assert client.patch(f"/api/business/staff/{mid}", headers=h, json={}).status_code == 422
    assert client.patch(f"/api/business/staff/{mid}", headers=h,
                        json={"is_active": None}).status_code == 422


# ---------- Password reset ----------

def test_reset_password_issues_new_temporary_password(client, biz, add_staff, db):
    attendant = add_staff(biz, S.ATTENDANT)
    mid = _membership_id(db, attendant)
    r = client.post(f"/api/business/staff/{mid}/reset-password", headers=auth_header(biz.owner))
    assert r.status_code == 200
    temp = r.json()["temporary_password"]

    assert attendant.must_change_password is True
    assert login(client, attendant.email, PASSWORD).status_code == 401
    r = login(client, attendant.email, temp)
    assert r.status_code == 200 and r.json()["must_change_password"] is True
    assert db.scalar(select(AuditLog).where(AuditLog.action == "staff.password_reset"))
