"""POPIA rights: download my data (s23) and delete my account (s24)."""

import time
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core import mfa
from app.models import (
    AuditLog,
    DriverLocation,
    Notification,
    Order,
    OrderItem,
    Review,
    User,
    VerificationDocument,
)
from app.models.enums import AccountStatus, BusinessStaffRole as S, JobKind, UserRole
from tests.conftest import PASSWORD, auth_header, pay
from tests.test_driver_flow import (  # noqa: F401 (fixtures are used by name)
    AT_HOME,
    accepted_order,
    collect,
    customer,
    customer_code,
    driver,
    job_of,
    laundry,
    online_driver,
    take,
)
from tests.test_orders import order_body, place

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def delete_me(client, user, password=PASSWORD, confirm="DELETE", code=None):
    body = {"password": password, "confirm": confirm} | ({"code": code} if code else {})
    return client.request("DELETE", "/api/me", headers=auth_header(user), json=body)


def finished_order(client, db, customer, laundry):
    """A delivered order with a review, without driving the whole flow."""
    from app.models.enums import OrderStatus
    o = place(client, customer, order_body(laundry, notes="Gate code 4321")).json()
    pay(client, customer, o)
    order = db.get(Order, o["id"])
    order.status = OrderStatus.DELIVERED
    db.add(Review(order_id=order.id, customer_id=customer.id, target="business",
                  business_id=order.business_id, rating=4, comment="Lovely, but late"))
    db.flush()
    return o


# ---------- Download my data ----------

def test_export_contains_my_data_only(client, db, customer, laundry, make_user):
    o = finished_order(client, db, customer, laundry)
    other = make_user(UserRole.CUSTOMER)
    place(client, other, order_body(laundry))

    r = client.get("/api/me/data-export", headers=auth_header(customer))
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    data = r.json()
    assert data["account"]["email"] == customer.email
    assert [x["order_number"] for x in data["orders"]] == [o["order_number"]]
    assert data["orders"][0]["notes"] == "Gate code 4321"
    assert data["orders"][0]["payments"][0]["status"] == "paid"
    assert data["reviews_written"][0]["comment"] == "Lovely, but late"
    assert data["notifications"]  # e.g. payment received
    assert data["security_log"]
    assert other.email not in r.text
    assert "password" not in r.text.lower().replace("must_change_password", "")
    assert db.scalar(select(AuditLog).where(AuditLog.action == "privacy.data_exported"))


def test_driver_export_includes_jobs_and_locations(client, db, customer, driver, accepted_order):
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    client.post(f"/api/driver/jobs/{job.id}/location", headers=auth_header(driver), json=AT_HOME)
    data = client.get("/api/me/data-export", headers=auth_header(driver)).json()
    assert data["driver_profile"]["vehicle_registration"] == "GP 123-456"
    assert data["driver_jobs"][0]["order_number"] == accepted_order["order_number"]
    assert data["location_history"][0]["latitude"] == AT_HOME["latitude"]
    assert customer.full_name not in str(data)  # other people's details stay out


# ---------- Delete my account ----------

def test_customer_deletes_account(client, db, customer, laundry):
    from app.models import CustomerProfile
    customer.customer_profile = CustomerProfile(address_line="12 Pritchard St", city="Johannesburg",
                                                latitude=-26.2041, longitude=28.0473)
    db.flush()
    o = finished_order(client, db, customer, laundry)
    email = customer.email
    old_token = auth_header(customer)
    total = db.get(Order, o["id"]).total_cents

    r = delete_me(client, customer)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] is True
    assert body["removed"]["orders_anonymised"] == 1
    assert any("tax" in k for k in body["kept"])

    # Personal details are gone
    db.refresh(customer)
    assert customer.full_name == "Deleted user"
    assert customer.email.endswith("@deleted.invalid") and customer.phone is None
    assert customer.status == AccountStatus.DEACTIVATED and customer.deleted_at is not None
    assert customer.customer_profile.address_line is None

    # Can't log in, old sessions are dead
    assert client.post("/api/auth/login", data={"username": email, "password": PASSWORD}).status_code == 401
    assert client.get("/api/auth/me", headers=old_token).status_code in (401, 403)

    # Financial record kept, but without street, notes or exact location
    order = db.get(Order, o["id"])
    assert order.total_cents == total and order.paid_cents == total
    assert order.collection_address_line.startswith("(removed")
    assert order.customer_notes is None
    assert order.collection_latitude == round(order.collection_latitude, 2)
    assert order.collection_suburb == "Marshalltown"  # area kept for the records
    assert db.scalar(select(OrderItem).where(OrderItem.order_id == order.id)) is not None

    # Review: rating stays, comment goes; notifications gone
    review = db.scalar(select(Review).where(Review.order_id == order.id))
    assert review.rating == 4 and review.comment is None
    assert db.scalar(select(Notification).where(Notification.user_id == customer.id)) is None
    assert db.scalar(select(AuditLog).where(AuditLog.action == "privacy.account_deleted"))

    # The email address is free to register again
    assert db.scalar(select(User).where(User.email == email)) is None


def test_wrong_password_or_no_confirmation(client, db, customer):
    assert delete_me(client, customer, password="not-it").status_code == 400
    assert delete_me(client, customer, confirm="yes").status_code == 422
    db.refresh(customer)
    assert customer.deleted_at is None


def test_mfa_code_needed_when_enabled(client, customer):
    h = auth_header(customer)
    secret = client.post("/api/auth/mfa/setup", headers=h).json()["secret"]
    client.post("/api/auth/mfa/enable", headers=h, json={"code": mfa.code_for(secret)})
    assert delete_me(client, customer).status_code == 400
    code = mfa.code_for(secret, time.time() + mfa.STEP_SECONDS)
    assert delete_me(client, customer, code=code).status_code == 200


def test_blocked_while_an_order_is_in_progress(client, customer, accepted_order):
    r = delete_me(client, customer)
    assert r.status_code == 409
    assert accepted_order["order_number"] in r.json()["detail"]


def test_driver_blocked_during_active_job(client, db, driver, accepted_order):
    take(client, driver, job_of(db, accepted_order, JobKind.COLLECTION))
    r = delete_me(client, driver)
    assert r.status_code == 409 and "active delivery job" in r.json()["detail"]


def test_laundry_owner_must_hand_over_first(client, laundry):
    r = delete_me(client, laundry.owner)
    assert r.status_code == 409 and "own a laundry" in r.json()["detail"]


def test_admins_cannot_self_delete(client, make_user):
    assert delete_me(client, make_user(UserRole.ADMIN)).status_code == 409


def test_staff_member_can_leave(client, laundry, add_staff, db):
    attendant = add_staff(laundry, S.ATTENDANT)
    assert delete_me(client, attendant).status_code == 200
    assert attendant.staff_membership.is_active is False


def test_driver_documents_and_locations_removed(client, db, driver, isolated_uploads, customer,
                                                accepted_order):
    r = client.post("/api/documents", headers=auth_header(driver), data={"document_type": "selfie"},
                    files={"file": ("me.png", PNG, "image/png")})
    path = isolated_uploads / db.get(VerificationDocument, r.json()["id"]).file_path
    assert Path(path).exists()

    # A finished trip with a location ping (no open incident about it)
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    client.post(f"/api/driver/jobs/{job.id}/location", headers=auth_header(driver), json=AT_HOME)
    collect(client, driver, job, customer_code(client, customer, accepted_order))
    from app.models.enums import JobStatus
    job.status = JobStatus.COMPLETED
    db.flush()

    body = delete_me(client, driver).json()
    assert body["removed"]["identity_documents"] == 1
    assert body["removed"]["location_points"] == 1
    assert not Path(path).exists()
    assert db.scalar(select(VerificationDocument).where(VerificationDocument.user_id == driver.id)) is None
    db.refresh(driver)
    assert driver.driver_profile.id_number.startswith("DELETED-")
    assert db.scalar(select(DriverLocation).where(DriverLocation.driver_id == driver.id)) is None


def test_locations_kept_while_under_investigation(client, db, customer, driver, accepted_order):
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    client.post(f"/api/driver/jobs/{job.id}/location", headers=auth_header(driver), json=AT_HOME)
    collect(client, driver, job, customer_code(client, customer, accepted_order))
    client.post("/api/incidents", headers=auth_header(customer), json={
        "order_id": accepted_order["id"], "category": "missing_items",
        "description": "A shirt went missing on the way to the laundry."})
    from app.models.enums import JobStatus
    job.status = JobStatus.COMPLETED
    db.flush()

    body = delete_me(client, driver).json()
    assert body["removed"]["location_points"] == 0  # evidence for the open case
    assert db.scalar(select(DriverLocation).where(DriverLocation.driver_id == driver.id))


def test_deleted_user_still_shows_as_anonymous_on_old_records(client, db, customer, laundry):
    o = finished_order(client, db, customer, laundry)
    delete_me(client, customer)
    reviews = client.get(f"/api/laundries/{laundry.id}/reviews").json()
    assert reviews[0]["reviewer"] == "Deleted"
    assert db.get(User, customer.id) is not None  # row kept for the retained records
    assert db.get(Order, o["id"]).customer_id == customer.id


@pytest.mark.parametrize("path", ["/api/me/data-export"])
def test_requires_login(client, path):
    assert client.get(path).status_code == 401
