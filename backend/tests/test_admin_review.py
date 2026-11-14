"""Admin approval / rejection of drivers and businesses (UR-004, UAT-005)."""

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.models.enums import UserRole, VerificationStatus as V
from tests.conftest import auth_header

REASON = "ID document photo is blurry, please re-upload"


@pytest.fixture
def admin(make_user):
    return make_user(UserRole.ADMIN)


def me(client, user):
    return client.get("/api/auth/me", headers=auth_header(user)).json()


# ---------- Access ----------

@pytest.mark.parametrize("role", [UserRole.CUSTOMER, UserRole.DRIVER, UserRole.BUSINESS])
def test_non_admins_cannot_use_review_endpoints(client, make_user, make_driver, role):
    user = make_user(role)
    driver = make_driver()
    h = auth_header(user)
    assert client.get("/api/admin/drivers", headers=h).status_code == 403
    assert client.get("/api/admin/businesses", headers=h).status_code == 403
    assert client.post(f"/api/admin/drivers/{driver.id}/approve", headers=h).status_code == 403
    assert driver.driver_profile.verification_status == V.PENDING


def test_review_endpoints_require_login(client, make_driver):
    driver = make_driver()
    assert client.get("/api/admin/drivers").status_code == 401
    assert client.post(f"/api/admin/drivers/{driver.id}/approve").status_code == 401


# ---------- Listing ----------

def test_lists_pending_drivers_by_default(client, admin, make_driver):
    pending = [make_driver() for _ in range(3)]
    make_driver(V.APPROVED)

    r = client.get("/api/admin/drivers", headers=auth_header(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert {d["user_id"] for d in body["items"]} == {str(d.id) for d in pending}
    assert all(d["verification_status"] == "pending" for d in body["items"])


def test_filter_and_paginate_drivers(client, admin, make_driver):
    for _ in range(3):
        make_driver(V.APPROVED)
    h = auth_header(admin)

    page1 = client.get("/api/admin/drivers?status=approved&limit=2", headers=h).json()
    page2 = client.get("/api/admin/drivers?status=approved&limit=2&offset=2", headers=h).json()
    assert page1["total"] == page2["total"] == 3
    assert len(page1["items"]) == 2 and len(page2["items"]) == 1
    ids = {d["user_id"] for d in page1["items"] + page2["items"]}
    assert len(ids) == 3  # no overlap between pages


def test_lists_pending_businesses_with_owner(client, admin, make_business):
    biz = make_business(V.PENDING)
    make_business(V.APPROVED)
    body = client.get("/api/admin/businesses", headers=auth_header(admin)).json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(biz.id)
    assert body["items"][0]["owner_email"] == biz.owner.email


def test_unknown_ids_return_404(client, admin):
    h = auth_header(admin)
    missing = uuid.uuid4()
    assert client.get(f"/api/admin/drivers/{missing}", headers=h).status_code == 404
    assert client.post(f"/api/admin/drivers/{missing}/approve", headers=h).status_code == 404
    assert client.post(f"/api/admin/businesses/{missing}/approve", headers=h).status_code == 404


# ---------- Driver decisions ----------

def test_approve_driver(client, admin, make_driver, approve_required_docs, db):
    driver = make_driver()
    approve_required_docs(driver)
    r = client.post(f"/api/admin/drivers/{driver.id}/approve", headers=auth_header(admin))
    assert r.status_code == 200, r.text
    assert r.json()["verification_status"] == "approved"
    assert r.json()["verified_by_id"] == str(admin.id)

    assert me(client, driver)["driver"]["verification_status"] == "approved"

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "driver.approved"))
    assert entry.actor_user_id == admin.id
    assert entry.entity_id == str(driver.id)
    assert entry.details == {"previous_status": "pending"}


def test_reject_driver_requires_reason(client, admin, make_driver):
    driver = make_driver()
    h = auth_header(admin)
    assert client.post(f"/api/admin/drivers/{driver.id}/reject", headers=h).status_code == 422
    r = client.post(f"/api/admin/drivers/{driver.id}/reject", headers=h, json={"reason": "no"})
    assert r.status_code == 422
    assert driver.driver_profile.verification_status == V.PENDING


def test_rejected_driver_sees_reason(client, admin, make_driver, db):
    driver = make_driver()
    r = client.post(f"/api/admin/drivers/{driver.id}/reject",
                    headers=auth_header(admin), json={"reason": REASON})
    assert r.status_code == 200
    info = me(client, driver)["driver"]
    assert info["verification_status"] == "rejected"
    assert info["rejection_reason"] == REASON

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "driver.rejected"))
    assert entry.details["reason"] == REASON


def test_cannot_approve_twice_or_reject_twice(client, admin, make_driver, approve_required_docs):
    h = auth_header(admin)
    a, b = make_driver(), make_driver()
    approve_required_docs(a)
    assert client.post(f"/api/admin/drivers/{a.id}/approve", headers=h).status_code == 200
    assert client.post(f"/api/admin/drivers/{a.id}/approve", headers=h).status_code == 409
    assert client.post(f"/api/admin/drivers/{b.id}/reject", headers=h,
                       json={"reason": REASON}).status_code == 200
    assert client.post(f"/api/admin/drivers/{b.id}/reject", headers=h,
                       json={"reason": REASON}).status_code == 409


def test_revoking_approval_takes_driver_offline(client, admin, make_driver, db):
    driver = make_driver(V.APPROVED)
    driver.driver_profile.is_available = True
    db.flush()

    r = client.post(f"/api/admin/drivers/{driver.id}/reject",
                    headers=auth_header(admin), json={"reason": "Under investigation"})
    assert r.status_code == 200
    assert driver.driver_profile.is_available is False
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "driver.rejected"))
    assert entry.details["previous_status"] == "approved"


def test_rejected_driver_can_be_approved_after_fixing(client, admin, make_driver, approve_required_docs):
    driver = make_driver()
    approve_required_docs(driver)
    h = auth_header(admin)
    client.post(f"/api/admin/drivers/{driver.id}/reject", headers=h, json={"reason": REASON})
    r = client.post(f"/api/admin/drivers/{driver.id}/approve", headers=h)
    assert r.status_code == 200
    assert r.json()["rejection_reason"] is None  # old reason cleared


# ---------- Business decisions ----------

def test_approve_business_unlocks_staff_access(client, admin, make_business, approve_required_docs, db):
    biz = make_business(V.PENDING)
    approve_required_docs(biz.owner)
    r = client.post(f"/api/admin/businesses/{biz.id}/approve", headers=auth_header(admin))
    assert r.status_code == 200, r.text
    assert me(client, biz.owner)["business"]["business_verification_status"] == "approved"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "business.approved"))


def test_reject_business_shows_reason_to_owner(client, admin, make_business):
    biz = make_business(V.PENDING)
    r = client.post(f"/api/admin/businesses/{biz.id}/reject",
                    headers=auth_header(admin), json={"reason": "CIPC number not found"})
    assert r.status_code == 200
    info = me(client, biz.owner)["business"]
    assert info["business_verification_status"] == "rejected"
    assert info["business_rejection_reason"] == "CIPC number not found"
