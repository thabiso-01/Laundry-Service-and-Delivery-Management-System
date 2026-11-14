"""Businesses manage incoming orders (UR-010, UR-011, SEC-017, Business Rules 2 & 8)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, Order
from app.models.enums import BusinessStaffRole as S
from app.models.enums import OrderStatus, UserRole
from app.models.enums import VerificationStatus as V
from tests.conftest import auth_header, pay
from tests.test_driver_flow import weigh_as_estimated
from tests.test_orders import LAUNDRY, order_body, place


@pytest.fixture
def customer(make_user):
    return make_user(UserRole.CUSTOMER)


@pytest.fixture
def laundry(make_laundry):
    return make_laundry(*LAUNDRY)


@pytest.fixture
def order(client, customer, laundry):
    r = place(client, customer, order_body(laundry))
    assert r.status_code == 201, r.text
    pay(client, customer, r.json())
    return r.json()


def url(order, action=""):
    return f"/api/business/orders/{order['id']}" + (f"/{action}" if action else "")


def set_status(db, order, status):
    db.get(Order, order["id"]).status = status
    db.flush()


# ---------- Viewing ----------

def test_staff_see_their_incoming_orders(client, laundry, add_staff, order):
    attendant = add_staff(laundry, S.ATTENDANT)
    page = client.get("/api/business/orders", headers=auth_header(attendant)).json()
    assert page["total"] == 1
    assert page["items"][0]["order_number"] == order["order_number"]


def test_order_detail_includes_customer_contact(client, laundry, customer, order):
    customer.phone = "+27821234567"
    r = client.get(url(order), headers=auth_header(laundry.owner))
    assert r.status_code == 200
    body = r.json()
    assert body["customer_name"] == customer.full_name
    assert body["customer_phone"] == "+27821234567"
    assert customer.email not in r.text  # only the contact details they need


def test_finished_orders_hidden_by_default(client, laundry, order, db):
    set_status(db, order, OrderStatus.DELIVERED)
    h = auth_header(laundry.owner)
    assert client.get("/api/business/orders", headers=h).json()["total"] == 0
    done = client.get("/api/business/orders?status=delivered", headers=h).json()
    assert done["total"] == 1


def test_summary_counts(client, laundry, customer, order):
    place(client, customer, order_body(laundry))
    counts = client.get("/api/business/orders/summary",
                        headers=auth_header(laundry.owner)).json()["counts"]
    assert counts["placed"] == 2
    assert counts["ready"] == 0


# ---------- Isolation and verification ----------

def test_other_business_cannot_see_or_touch_order(client, make_laundry, order):
    other = make_laundry()
    h = auth_header(other.owner)
    assert client.get(url(order), headers=h).status_code == 404
    assert client.post(url(order, "accept"), headers=h).status_code == 404
    assert client.get("/api/business/orders", headers=h).json()["total"] == 0


def test_unverified_business_cannot_manage_orders(client, laundry, order, db):
    laundry.verification_status = V.PENDING  # e.g. approval revoked
    db.flush()
    assert client.get("/api/business/orders",
                      headers=auth_header(laundry.owner)).status_code == 403


@pytest.mark.parametrize("role", [UserRole.CUSTOMER, UserRole.DRIVER, UserRole.ADMIN])
def test_non_business_users_blocked(client, make_user, order, role):
    assert client.post(url(order, "accept"),
                       headers=auth_header(make_user(role))).status_code == 403


# ---------- Accept / decline ----------

def test_attendant_accepts_order_and_is_recorded(client, laundry, add_staff, customer, order, db):
    attendant = add_staff(laundry, S.ATTENDANT)
    r = client.post(url(order, "accept"), headers=auth_header(attendant))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "accepted"
    last = body["history"][-1]
    assert (last["from_status"], last["to_status"]) == ("placed", "accepted")
    assert last["actor_name"] == attendant.full_name
    assert last["actor_role"] == "attendant"

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "order.accepted"))
    assert entry.actor_user_id == attendant.id

    # The customer sees the new status too
    mine = client.get(f"/api/orders/{order['id']}", headers=auth_header(customer)).json()
    assert mine["status"] == "accepted"


def test_cannot_accept_twice(client, laundry, order):
    h = auth_header(laundry.owner)
    assert client.post(url(order, "accept"), headers=h).status_code == 200
    assert client.post(url(order, "accept"), headers=h).status_code == 409


def test_cannot_accept_cancelled_order(client, laundry, customer, order):
    client.post(f"/api/orders/{order['id']}/cancel", headers=auth_header(customer))
    r = client.post(url(order, "accept"), headers=auth_header(laundry.owner))
    assert r.status_code == 409
    assert "cancelled" in r.json()["detail"]


def test_cannot_accept_after_collection_time_passed(client, laundry, order, db):
    o = db.get(Order, order["id"])
    shift = o.collection_window_start - (datetime.now(UTC) - timedelta(hours=1))
    # move the whole schedule into the past, keeping it internally consistent
    for f in ("collection_window_start", "collection_window_end",
              "delivery_window_start", "delivery_window_end"):
        setattr(o, f, getattr(o, f) - shift)
    db.flush()
    r = client.post(url(order, "accept"), headers=auth_header(laundry.owner))
    assert r.status_code == 409
    assert "decline" in r.json()["detail"]


def test_decline_requires_reason_shown_to_customer(client, laundry, customer, order, db):
    h = auth_header(laundry.owner)
    assert client.post(url(order, "decline"), headers=h).status_code == 422
    r = client.post(url(order, "decline"), headers=h,
                    json={"reason": "Fully booked this weekend"})
    assert r.status_code == 200 and r.json()["status"] == "declined"

    mine = client.get(f"/api/orders/{order['id']}", headers=auth_header(customer)).json()
    assert mine["declined_reason"] == "Fully booked this weekend"
    assert mine["history"][-1]["note"] == "Fully booked this weekend"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "order.declined"))


def test_customer_cannot_cancel_declined_order(client, laundry, customer, order):
    client.post(url(order, "decline"), headers=auth_header(laundry.owner),
                json={"reason": "Fully booked"})
    assert client.post(f"/api/orders/{order['id']}/cancel",
                       headers=auth_header(customer)).status_code == 409


# ---------- Processing ----------

def test_received_order_moves_to_processing_then_ready(client, laundry, add_staff, order, db):
    set_status(db, order, OrderStatus.RECEIVED)  # handover via QR scan comes in Phase 3
    attendant = add_staff(laundry, S.ATTENDANT)
    h = auth_header(attendant)

    r = client.post(url(order, "status"), headers=h, json={"status": "processing"})
    assert r.status_code == 200, r.text
    weigh_as_estimated(client, laundry, order)
    r = client.post(url(order, "status"), headers=h,
                    json={"status": "ready", "note": "Packed in 2 bags"})
    assert r.json()["status"] == "ready"
    assert r.json()["history"][-1]["note"] == "Packed in 2 bags"

    changes = db.scalars(select(AuditLog.details).where(
        AuditLog.action == "order.status_changed")).all()
    assert [(c["from"], c["to"]) for c in changes] == [
        ("received", "processing"), ("processing", "ready")]


@pytest.mark.parametrize("current,target", [
    (OrderStatus.ACCEPTED, "processing"),   # not received yet
    (OrderStatus.RECEIVED, "ready"),        # can't skip processing
    (OrderStatus.READY, "processing"),      # can't go backwards
    (OrderStatus.CANCELLED, "processing"),
])
def test_invalid_transitions_rejected(client, laundry, order, db, current, target):
    set_status(db, order, current)
    r = client.post(url(order, "status"), headers=auth_header(laundry.owner),
                    json={"status": target})
    assert r.status_code == 409


@pytest.mark.parametrize("target", ["collected", "received", "delivered", "out_for_delivery"])
def test_handover_statuses_cannot_be_set_directly(client, laundry, order, db, target):
    # These need OTP / QR verification (SEC-007, SEC-011), not a button press
    set_status(db, order, OrderStatus.ACCEPTED)
    r = client.post(url(order, "status"), headers=auth_header(laundry.owner),
                    json={"status": target})
    assert r.status_code == 422
