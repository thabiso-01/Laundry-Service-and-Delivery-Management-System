"""Placing, viewing and cancelling orders (UR-007, UR-008, UR-012, UR-013, SEC-009, SEC-042)."""

import re
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog, Order, OrderItem
from app.models.enums import AccountStatus, OrderStatus, UserRole
from app.models.enums import VerificationStatus as V
from app.services.orders import SAST, delivery_fee
from app.services.search import haversine_km
from tests.conftest import auth_header

HOME = {"address_line": "12 Pritchard St", "suburb": "Marshalltown", "city": "Johannesburg",
        "latitude": -26.2041, "longitude": 28.0473}
LAUNDRY = (-26.1929, 28.0305)


def at(days: int, hour: int, minute: int = 0) -> datetime:
    base = datetime.now(SAST).replace(hour=0, minute=0, second=0, microsecond=0)
    return base + timedelta(days=days, hours=hour, minutes=minute)


def window(start: datetime, hours: int = 2) -> dict:
    return {"start": start.isoformat(), "end": (start + timedelta(hours=hours)).isoformat()}


@pytest.fixture
def customer(make_user):
    return make_user(UserRole.CUSTOMER)


@pytest.fixture
def laundry(make_laundry):
    return make_laundry(*LAUNDRY, services=[
        ("Wash & Fold", "wash_and_fold", "per_kg", 2500, 48, 3),
        ("Duvet", "bedding", "per_item", 15000, 72),
        ("Suit", "dry_cleaning", "per_item", 12000, 24),
    ])


def service_id(biz, name):
    return str(next(s.id for s in biz.services if s.name == name))


def order_body(biz, **overrides):
    body = {
        "business_id": str(biz.id),
        "items": [{"service_id": service_id(biz, "Wash & Fold"), "quantity": 5}],
        "collection_address": HOME,
        "collection_window": window(at(2, 9)),
        "delivery_window": window(at(4, 12)),  # collection ends 11:00 + 48 h turnaround
    }
    return body | overrides


def place(client, user, body):
    return client.post("/api/orders", headers=auth_header(user), json=body)


def expected_fee():
    one_way = haversine_km(HOME["latitude"], HOME["longitude"], *LAUNDRY)
    return delivery_fee(round(one_way * 2, 2))


# ---------- Quote ----------

def test_quote_prices_without_placing(client, customer, laundry, db):
    r = client.post("/api/orders/quote", headers=auth_header(customer), json=order_body(laundry))
    assert r.status_code == 200, r.text
    q = r.json()
    assert q["subtotal_cents"] == 5 * 2500
    assert q["delivery_fee_cents"] == expected_fee()
    assert q["total_cents"] == 12500 + expected_fee()
    assert q["is_estimate"] is True  # priced per kg
    assert q["total_display"].endswith("(estimate)")
    assert q["items"][0]["description"] == "5 kg × R25.00"
    assert db.scalar(select(Order)) is None


# ---------- Placing ----------

def test_customer_places_order(client, customer, laundry, db):
    body = order_body(laundry, items=[
        {"service_id": service_id(laundry, "Wash & Fold"), "quantity": 4},
        {"service_id": service_id(laundry, "Duvet"), "quantity": 2},
    ], notes="Gate code 1234", delivery_window=window(at(5, 12)))  # duvet takes 72 h
    r = place(client, customer, body)
    assert r.status_code == 201, r.text
    o = r.json()

    assert re.fullmatch(r"LC-[0-9A-HJKMNP-TV-Z]{8}", o["order_number"])
    assert o["status"] == "placed"
    assert o["subtotal_cents"] == 4 * 2500 + 2 * 15000
    assert o["total_cents"] == o["subtotal_cents"] + o["delivery_fee_cents"]
    assert [i["service_name"] for i in o["items"]] == ["Wash & Fold", "Duvet"]
    assert o["delivery_address"] == o["collection_address"]  # defaults to collection
    assert o["notes"] == "Gate code 1234"
    assert [(e["from_status"], e["to_status"]) for e in o["history"]] == [(None, "placed")]

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "order.placed"))
    assert entry.actor_user_id == customer.id
    assert entry.details["order_number"] == o["order_number"]


def test_order_numbers_are_unique(client, customer, laundry):
    numbers = {place(client, customer, order_body(laundry)).json()["order_number"]
               for _ in range(5)}
    assert len(numbers) == 5


def test_per_item_only_order_is_not_an_estimate(client, customer, laundry):
    body = order_body(laundry, items=[{"service_id": service_id(laundry, "Suit"), "quantity": 1}],
                      delivery_window=window(at(3, 12)))
    assert place(client, customer, body).json()["is_estimate"] is False


def test_different_delivery_address_changes_fee(client, customer, laundry):
    near = place(client, customer, order_body(laundry)).json()
    far = place(client, customer, order_body(laundry, delivery_address={
        **HOME, "address_line": "1 Sandton Dr", "latitude": -26.1076, "longitude": 28.0567,
    })).json()
    assert far["delivery_fee_cents"] > near["delivery_fee_cents"]
    assert far["delivery_address"]["address_line"] == "1 Sandton Dr"


# ---------- Prices are frozen (SEC-042) ----------

def test_later_price_change_does_not_affect_order(client, customer, laundry, db):
    o = place(client, customer, order_body(laundry)).json()
    wash = next(s for s in laundry.services if s.name == "Wash & Fold")
    wash.price_cents = 9999
    db.flush()
    r = client.get(f"/api/orders/{o['id']}", headers=auth_header(customer))
    assert r.json()["items"][0]["unit_price_cents"] == 2500
    assert r.json()["total_cents"] == o["total_cents"]


def test_client_cannot_send_prices(client, customer, laundry):
    body = order_body(laundry, items=[
        {"service_id": service_id(laundry, "Wash & Fold"), "quantity": 5, "unit_price_cents": 1}])
    assert place(client, customer, body).status_code == 422
    assert place(client, customer, order_body(laundry, total_cents=1)).status_code == 422


def _expect_db_refusal(db, sql):
    sp = db.begin_nested()
    with pytest.raises(DBAPIError):
        db.execute(text(sql))
    sp.rollback()


def test_database_refuses_to_edit_order_lines(client, customer, laundry, db):
    place(client, customer, order_body(laundry))
    _expect_db_refusal(db, "UPDATE order_items SET unit_price_cents = 1")
    _expect_db_refusal(db, "DELETE FROM order_items")
    _expect_db_refusal(db, "UPDATE order_status_events SET note = 'edited'")


def test_database_refuses_totals_that_dont_add_up(client, customer, laundry, db):
    place(client, customer, order_body(laundry))
    _expect_db_refusal(db, "UPDATE orders SET total_cents = 1")


# ---------- Who may order ----------

@pytest.mark.parametrize("role", [UserRole.DRIVER, UserRole.BUSINESS, UserRole.ADMIN])
def test_only_customers_can_order(client, make_user, laundry, role):
    assert place(client, make_user(role), order_body(laundry)).status_code == 403


def test_must_be_logged_in(client, laundry):
    assert client.post("/api/orders", json=order_body(laundry)).status_code == 401


@pytest.mark.parametrize("status", [V.PENDING, V.REJECTED])
def test_cannot_order_from_unverified_laundry(client, customer, make_laundry, status):
    biz = make_laundry()
    biz.verification_status = status
    assert place(client, customer, order_body(biz)).status_code == 404


def test_cannot_order_from_suspended_business(client, customer, laundry, db):
    laundry.owner.status = AccountStatus.SUSPENDED
    db.flush()
    assert place(client, customer, order_body(laundry)).status_code == 404


# ---------- Item validation ----------

def test_service_from_another_laundry_rejected(client, customer, laundry, make_laundry):
    other = make_laundry()
    body = order_body(laundry, items=[{"service_id": str(other.services[0].id), "quantity": 5}])
    assert place(client, customer, body).status_code == 422


def test_inactive_service_rejected(client, customer, laundry, db):
    next(s for s in laundry.services if s.name == "Wash & Fold").is_active = False
    db.flush()
    assert place(client, customer, order_body(laundry)).status_code == 422


def test_minimum_quantity_enforced(client, customer, laundry):
    body = order_body(laundry, items=[{"service_id": service_id(laundry, "Wash & Fold"),
                                       "quantity": 2}])
    r = place(client, customer, body)
    assert r.status_code == 422
    assert "minimum of 3 kg" in r.json()["detail"]


def test_duplicate_service_lines_rejected(client, customer, laundry):
    line = {"service_id": service_id(laundry, "Wash & Fold"), "quantity": 3}
    assert place(client, customer, order_body(laundry, items=[line, line])).status_code == 422


# ---------- Scheduling (UR-008) ----------

@pytest.mark.parametrize("collection", [
    window(datetime.now(SAST) - timedelta(hours=3)),   # in the past
    window(datetime.now(SAST) + timedelta(minutes=10)),  # too soon
    window(at(20, 9)),                                   # more than 14 days ahead
    window(at(2, 9), hours=6),                           # window too long
    {"start": at(2, 9).isoformat(), "end": at(2, 9, 30).isoformat()},  # too short
    window(at(2, 5)),                                    # before 07:00
    window(at(2, 19)),                                   # ends after 20:00
], ids=["past", "too-soon", "too-far", "too-long", "too-short", "too-early", "too-late"])
def test_invalid_collection_window(client, customer, laundry, collection):
    body = order_body(laundry, collection_window=collection, delivery_window=window(at(25, 9)))
    assert place(client, customer, body).status_code == 422


def test_window_needs_timezone(client, customer, laundry):
    naive = {"start": "2030-01-01T09:00:00", "end": "2030-01-01T11:00:00"}
    assert place(client, customer, order_body(laundry, collection_window=naive)).status_code == 422


def test_delivery_cannot_be_before_laundry_is_ready(client, customer, laundry):
    # 48 h turnaround: collected by day 2 11:00 → earliest delivery day 4 11:00
    r = place(client, customer, order_body(laundry, delivery_window=window(at(3, 9))))
    assert r.status_code == 422
    assert "Earliest delivery" in r.json()["detail"]


def test_slowest_service_sets_earliest_delivery(client, customer, laundry):
    # Duvet takes 72 h, so day 4 is too early even though wash only needs 48 h
    body = order_body(laundry, items=[
        {"service_id": service_id(laundry, "Wash & Fold"), "quantity": 3},
        {"service_id": service_id(laundry, "Duvet"), "quantity": 1},
    ])
    assert place(client, customer, body).status_code == 422
    body["delivery_window"] = window(at(5, 12))
    assert place(client, customer, body).status_code == 201


def test_address_too_far_from_laundry(client, customer, laundry):
    pretoria = {**HOME, "city": "Pretoria", "latitude": -25.7479, "longitude": 28.2293}
    r = place(client, customer, order_body(laundry, collection_address=pretoria))
    assert r.status_code == 422
    assert "only collects within 30 km" in r.json()["detail"]


# ---------- Viewing ----------

def test_order_history_shows_only_my_orders(client, customer, make_user, laundry):
    other = make_user(UserRole.CUSTOMER)
    mine = place(client, customer, order_body(laundry)).json()
    place(client, other, order_body(laundry))

    page = client.get("/api/orders", headers=auth_header(customer)).json()
    assert page["total"] == 1
    assert page["items"][0]["order_number"] == mine["order_number"]
    assert page["items"][0]["business_name"] == "Braam Laundry"


def test_cannot_view_another_customers_order(client, customer, make_user, laundry):
    o = place(client, customer, order_body(laundry)).json()
    other = make_user(UserRole.CUSTOMER)
    assert client.get(f"/api/orders/{o['id']}", headers=auth_header(other)).status_code == 404
    assert client.post(f"/api/orders/{o['id']}/cancel",
                       headers=auth_header(other)).status_code == 404


# ---------- Cancelling ----------

def test_cancel_placed_order(client, customer, laundry, db):
    o = place(client, customer, order_body(laundry)).json()
    r = client.post(f"/api/orders/{o['id']}/cancel", headers=auth_header(customer),
                    json={"reason": "Changed my mind"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "cancelled"
    assert body["cancelled_reason"] == "Changed my mind"
    assert [e["to_status"] for e in body["history"]] == ["placed", "cancelled"]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "order.cancelled"))

    again = client.post(f"/api/orders/{o['id']}/cancel", headers=auth_header(customer))
    assert again.status_code == 409


def test_cannot_cancel_after_collection(client, customer, laundry, db):
    o = place(client, customer, order_body(laundry)).json()
    db.get(Order, o["id"]).status = OrderStatus.COLLECTED
    db.flush()
    r = client.post(f"/api/orders/{o['id']}/cancel", headers=auth_header(customer))
    assert r.status_code == 409
    assert "collected" in r.json()["detail"]
