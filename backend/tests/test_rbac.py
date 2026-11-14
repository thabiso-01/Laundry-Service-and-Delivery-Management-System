"""Role-based access control (SEC-018 – SEC-020, UAT-014).

There are no real feature routes yet, so these tests attach small test-only
routes that use the same dependencies the real routes will use.
"""

from typing import Annotated

import pytest
from fastapi import APIRouter, Depends

from app.api.deps import ApprovedDriver, require_admin, require_business_staff, require_customer
from app.main import app
from app.models import BusinessStaff
from app.models.enums import BusinessStaffRole as S, UserRole, VerificationStatus as V
from tests.conftest import auth_header

probe = APIRouter(prefix="/_test")


@probe.get("/admin", dependencies=[Depends(require_admin)])
def admin_only():
    return {"ok": True}


@probe.get("/customer", dependencies=[Depends(require_customer)])
def customer_only():
    return {"ok": True}


@probe.get("/driver-jobs")
def driver_jobs(driver: ApprovedDriver):
    return {"ok": True}


@probe.get("/orders")
def business_orders(staff: Annotated[BusinessStaff, Depends(require_business_staff())]):
    return {"business_id": str(staff.business_id)}


@probe.get("/manage-staff")
def manage_staff(staff: Annotated[BusinessStaff, Depends(require_business_staff(S.MANAGER))]):
    return {"ok": True}


@probe.get("/upload-docs")
def upload_docs(
    staff: Annotated[BusinessStaff, Depends(require_business_staff(business_must_be_verified=False))],
):
    return {"ok": True}


app.include_router(probe)


@pytest.mark.parametrize("role,expected", [
    (UserRole.ADMIN, 200),
    (UserRole.CUSTOMER, 403),
    (UserRole.DRIVER, 403),
    (UserRole.BUSINESS, 403),
])
def test_only_admins_reach_admin_routes(client, make_user, role, expected):
    user = make_user(role)
    assert client.get("/_test/admin", headers=auth_header(user)).status_code == expected


def test_admin_is_not_automatically_a_customer(client, make_user):
    admin = make_user(UserRole.ADMIN)
    assert client.get("/_test/customer", headers=auth_header(admin)).status_code == 403


@pytest.mark.parametrize("status,expected", [
    (V.PENDING, 403),
    (V.REJECTED, 403),
    (V.APPROVED, 200),
])
def test_only_approved_drivers_can_take_jobs(client, make_driver, status, expected):
    driver = make_driver(status)
    assert client.get("/_test/driver-jobs", headers=auth_header(driver)).status_code == expected


def test_customer_cannot_take_driver_jobs(client, make_user):
    customer = make_user(UserRole.CUSTOMER)
    assert client.get("/_test/driver-jobs", headers=auth_header(customer)).status_code == 403


def test_unverified_business_cannot_handle_orders(client, make_business):
    biz = make_business(V.PENDING)
    r = client.get("/_test/orders", headers=auth_header(biz.owner))
    assert r.status_code == 403
    assert "verification" in r.json()["detail"]


def test_unverified_business_can_still_upload_documents(client, make_business):
    biz = make_business(V.PENDING)
    assert client.get("/_test/upload-docs", headers=auth_header(biz.owner)).status_code == 200


def test_staff_are_scoped_to_their_business(client, make_business, add_staff):
    biz = make_business()
    attendant = add_staff(biz, S.ATTENDANT)
    r = client.get("/_test/orders", headers=auth_header(attendant))
    assert r.status_code == 200
    assert r.json()["business_id"] == str(biz.id)


@pytest.mark.parametrize("role,expected", [
    (S.ATTENDANT, 403),
    (S.MANAGER, 200),
    (S.OWNER, 200),
])
def test_staff_role_levels(client, make_business, add_staff, role, expected):
    biz = make_business()
    user = biz.owner if role == S.OWNER else add_staff(biz, role)
    assert client.get("/_test/manage-staff", headers=auth_header(user)).status_code == expected


def test_deactivated_staff_are_blocked(client, make_business, add_staff):
    biz = make_business()
    former = add_staff(biz, S.MANAGER, active=False)
    assert client.get("/_test/orders", headers=auth_header(former)).status_code == 403


def test_business_role_without_membership_is_blocked(client, make_user):
    loner = make_user(UserRole.BUSINESS)
    assert client.get("/_test/orders", headers=auth_header(loner)).status_code == 403
