"""Payments and final weighing (URS 2.1, SEC-042, Business Rule 11)."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog, Notification, Order, OrderItem, Payment, PaymentEvent
from app.models.enums import OrderStatus, PaymentStatus, UserRole
from app.services import payments
from tests.conftest import auth_header, pay
from tests.test_orders import LAUNDRY, order_body, place


@pytest.fixture
def customer(make_user):
    return make_user(UserRole.CUSTOMER)


@pytest.fixture
def laundry(make_laundry):
    return make_laundry(*LAUNDRY)


@pytest.fixture
def order(client, customer, laundry):
    return place(client, customer, order_body(laundry)).json()  # 5 kg wash, estimate


def checkout(client, customer, order):
    r = client.post(f"/api/orders/{order['id']}/pay", headers=auth_header(customer))
    assert r.status_code == 200, r.text
    return r.json()


def notify(client, payload):
    return client.post("/api/payments/notify", json=payload)


def signed(reference, amount, status="paid", provider_id="PF-1"):
    return {"reference": reference, "provider_payment_id": provider_id, "status": status,
            "amount_cents": amount,
            "signature": payments.sign(reference, provider_id, status, amount)}


def kinds(db, user):
    return [n.kind for n in db.scalars(select(Notification).where(Notification.user_id == user.id)
                                       .order_by(Notification.created_at))]


# ---------- Checkout and notifications from the provider ----------

def test_checkout_is_for_the_order_total_and_reused(client, customer, order):
    first = checkout(client, customer, order)
    assert first["amount_cents"] == order["total_cents"]
    assert first["reference"].startswith("PAY-")
    again = checkout(client, customer, order)
    assert again["reference"] == first["reference"]  # double-click safe


def test_paying_marks_order_paid_and_tells_everyone(client, db, customer, laundry, order):
    pay(client, customer, order)
    o = client.get(f"/api/orders/{order['id']}", headers=auth_header(customer)).json()
    assert o["paid_cents"] == o["total_cents"] and o["balance_cents"] == 0
    assert "payment.received" in kinds(db, customer)
    assert "order.new" in kinds(db, laundry.owner)
    history = client.get(f"/api/orders/{order['id']}/payments", headers=auth_header(customer))
    assert [p["status"] for p in history.json()] == ["paid"]


def test_unpaid_order_cannot_be_accepted(client, laundry, order):
    r = client.post(f"/api/business/orders/{order['id']}/accept",
                    headers=auth_header(laundry.owner))
    assert r.status_code == 409
    assert "paid" in r.json()["detail"]


def test_bad_signature_is_rejected_and_kept(client, db, customer, order):
    ref = checkout(client, customer, order)["reference"]
    forged = signed(ref, order["total_cents"]) | {"signature": "0" * 64}
    assert notify(client, forged).status_code == 400
    assert db.get(Order, order["id"]).paid_cents == 0
    event = db.scalar(select(PaymentEvent).where(PaymentEvent.reference == ref))
    assert event.outcome == "bad_signature" and event.signature_valid is False


def test_wrong_amount_never_marks_paid(client, db, customer, order):
    ref = checkout(client, customer, order)["reference"]
    r = notify(client, signed(ref, 100))  # correctly signed, but R1 instead of the total
    assert r.json()["outcome"] == "amount_mismatch"
    assert db.get(Order, order["id"]).paid_cents == 0
    assert db.scalar(select(AuditLog).where(AuditLog.action == "payment.amount_mismatch"))


def test_duplicate_notification_counts_once(client, db, customer, order):
    ref = checkout(client, customer, order)["reference"]
    note = signed(ref, order["total_cents"])
    assert notify(client, note).json()["outcome"] == "applied"
    assert notify(client, note).json()["outcome"] == "duplicate"
    assert db.get(Order, order["id"]).paid_cents == order["total_cents"]


def test_unknown_reference(client):
    assert notify(client, signed("PAY-NOPE", 100)).json()["outcome"] == "unknown_reference"


def test_failed_payment_can_be_retried(client, db, customer, order):
    ref = checkout(client, customer, order)["reference"]
    assert notify(client, signed(ref, order["total_cents"], "failed")).json()["outcome"] == "failed"
    assert db.scalar(select(Payment.status).where(Payment.reference == ref)) == PaymentStatus.FAILED
    assert "payment.failed" in kinds(db, customer)
    pay(client, customer, order)
    assert db.get(Order, order["id"]).paid_cents == order["total_cents"]


def test_nothing_to_pay_and_others_orders(client, customer, make_user, order):
    pay(client, customer, order)
    assert client.post(f"/api/orders/{order['id']}/pay",
                       headers=auth_header(customer)).status_code == 409
    stranger = make_user(UserRole.CUSTOMER)
    assert client.post(f"/api/orders/{order['id']}/pay",
                       headers=auth_header(stranger)).status_code == 404


def test_payment_events_are_permanent(client, db, customer, order):
    pay(client, customer, order)
    sp = db.begin_nested()
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE payment_events SET outcome = 'edited'"))
    sp.rollback()


def test_cancelling_a_paid_order_records_refund_due(client, db, customer, order):
    pay(client, customer, order)
    client.post(f"/api/orders/{order['id']}/cancel", headers=auth_header(customer))
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "payment.refund_due"))
    assert entry.details["amount_cents"] == order["total_cents"]


# ---------- Weighing (final price) ----------

@pytest.fixture
def received(client, db, customer, laundry, order):
    pay(client, customer, order)
    db.get(Order, order["id"]).status = OrderStatus.RECEIVED  # handover tested elsewhere
    db.flush()
    return order


def weigh(client, laundry, order, kg):
    wash = order["items"][0]["service_id"]
    return client.post(f"/api/business/orders/{order['id']}/weigh",
                       headers=auth_header(laundry.owner),
                       json={"lines": [{"service_id": wash, "actual_quantity": kg}]})


def ready(client, laundry, order):
    h = auth_header(laundry.owner)
    client.post(f"/api/business/orders/{order['id']}/status", headers=h,
                json={"status": "processing"})
    return client.post(f"/api/business/orders/{order['id']}/status", headers=h,
                       json={"status": "ready"})


def test_must_weigh_before_ready(client, laundry, received):
    r = ready(client, laundry, received)
    assert r.status_code == 409 and "Weigh" in r.json()["detail"]


def test_heavier_load_needs_balance_paid_before_ready(client, db, customer, laundry, received):
    r = weigh(client, laundry, received, 7)  # estimated 5 kg × R25 → 2 kg more
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["adjustment_cents"] == 2 * 2500
    assert body["balance_cents"] == 5000
    assert body["is_estimate"] is False
    assert "payment.balance_due" in kinds(db, customer)

    blocked = ready(client, laundry, received)
    assert blocked.status_code == 409 and "R50.00" in blocked.json()["detail"]

    balance = checkout(client, customer, received)
    assert balance["amount_cents"] == 5000  # only the difference
    pay(client, customer, received)
    assert ready(client, laundry, received).status_code == 200

    # The original order lines are untouched (SEC-042)
    item = db.scalar(select(OrderItem).where(OrderItem.order_id == received["id"]))
    assert item.quantity == 5


def test_lighter_load_means_refund(client, db, customer, laundry, received):
    body = weigh(client, laundry, received, 4).json()
    assert body["balance_cents"] == -2500
    assert "payment.refund_due" in kinds(db, customer)
    assert ready(client, laundry, received).status_code == 200


def test_weighing_rules(client, db, laundry, received, order):
    assert client.post(f"/api/business/orders/{order['id']}/weigh",
                       headers=auth_header(laundry.owner),
                       json={"lines": [{"service_id": order["business_id"],
                                        "actual_quantity": 5}]}).status_code == 422
    assert weigh(client, laundry, received, 5).status_code == 200
    assert weigh(client, laundry, received, 6).status_code == 409  # only once
    sp = db.begin_nested()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM order_adjustments"))
    sp.rollback()


def test_cannot_weigh_before_receiving(client, customer, laundry, order):
    pay(client, customer, order)
    assert weigh(client, laundry, order, 5).status_code == 409
