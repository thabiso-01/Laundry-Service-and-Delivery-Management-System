"""PayFast checkout signing and ITN notification checks. PayFast itself is never called."""

import hashlib
from urllib.parse import urlencode

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, Order, Payment, PaymentEvent
from app.models.enums import PaymentStatus, UserRole
from app.services import payfast
from tests.conftest import auth_header
from tests.test_orders import LAUNDRY, order_body, place

PASS = "test-salt-phrase"


@pytest.fixture
def payfast_on(monkeypatch):
    for name, value in {"payment_provider": "payfast", "payfast_merchant_id": "10000100",
                        "payfast_merchant_key": "46f0cd694581a", "payfast_passphrase": PASS,
                        "public_app_url": "https://app.example.co.za",
                        "public_api_url": "https://api.example.co.za"}.items():
        monkeypatch.setattr(settings, name, value)
    # PayFast's servers, as seen by the test client
    monkeypatch.setattr(payfast, "_resolve_hosts", lambda: {"testclient"})
    monkeypatch.setattr(payfast, "_confirm_with_payfast", lambda body: True)


# ---------- Signature rules (PayFast SDK, Auth::generateSignature) ----------

def test_param_string_matches_payfast_rules():
    pairs = [("merchant_id", "10000100"), ("return_url", "https://a.co.za/x?y=1"),
             ("name_first", " Thandi "), ("item_description", ""),  # trimmed / empty skipped
             ("item_name", "Wash & Fold ~ 5kg"), ("amount", "185.00")]
    expected = ("merchant_id=10000100&return_url=https%3A%2F%2Fa.co.za%2Fx%3Fy%3D1"
                "&name_first=Thandi&item_name=Wash+%26+Fold+%7E+5kg&amount=185.00"
                "&passphrase=my+salt")
    assert payfast.param_string(pairs, "my salt") == expected
    assert payfast.signature(pairs, "my salt") == hashlib.md5(expected.encode()).hexdigest()


def test_no_passphrase_means_none_appended():
    assert payfast.param_string([("a", "1")], "") == "a=1"


def test_amounts_always_have_two_decimals():
    assert [payfast.amount_text(c) for c in (18500, 1, 123456)] == ["185.00", "0.01", "1234.56"]


# ---------- Checkout ----------

def test_checkout_returns_a_signed_payfast_form(client, make_user, make_laundry, payfast_on):
    customer = make_user(UserRole.CUSTOMER)
    laundry = make_laundry(*LAUNDRY)
    order = place(client, customer, order_body(laundry)).json()
    r = client.post(f"/api/orders/{order['id']}/pay", headers=auth_header(customer))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "payfast"
    assert body["form_action"] == "https://sandbox.payfast.co.za/eng/process"
    fields = [tuple(f) for f in body["form_fields"]]
    names = [k for k, _ in fields]
    assert names == ["merchant_id", "merchant_key", "return_url", "cancel_url", "notify_url",
                     "name_first", "email_address", "m_payment_id", "amount", "item_name",
                     "signature"]  # PayFast's documented order, signature last
    values = dict(fields)
    assert values["amount"] == f"{order['total_cents'] / 100:.2f}"
    assert values["notify_url"] == "https://api.example.co.za/api/payments/payfast/notify"
    assert values["return_url"].startswith(f"https://app.example.co.za/orders/{order['id']}")
    assert values["signature"] == payfast.signature(fields[:-1], PASS)
    assert "phone" not in str(values)  # nothing beyond what PayFast needs


def test_checkout_without_credentials_is_refused(client, make_user, make_laundry, monkeypatch):
    monkeypatch.setattr(settings, "payment_provider", "payfast")
    monkeypatch.setattr(settings, "payfast_merchant_id", "")
    customer = make_user(UserRole.CUSTOMER)
    order = place(client, customer, order_body(make_laundry(*LAUNDRY))).json()
    r = client.post(f"/api/orders/{order['id']}/pay", headers=auth_header(customer))
    assert r.status_code == 503


# ---------- ITN (payment notification) ----------

@pytest.fixture
def pending(client, make_user, make_laundry, payfast_on, db):
    customer = make_user(UserRole.CUSTOMER)
    order = place(client, customer, order_body(make_laundry(*LAUNDRY))).json()
    client.post(f"/api/orders/{order['id']}/pay", headers=auth_header(customer))
    payment = db.scalar(select(Payment).where(Payment.order_id == order["id"]))
    return {"order": order, "payment": payment, "customer": customer}


def itn(payment, status="COMPLETE", amount=None, passphrase=PASS, extra=()):
    pairs = [("m_payment_id", payment.reference), ("pf_payment_id", "1234567"),
             ("payment_status", status), ("item_name", "LaundryConnect order"),
             ("amount_gross", amount or payfast.amount_text(payment.amount_cents)),
             ("amount_fee", "-4.26"), ("amount_net", "180.74"),
             ("name_first", "Thandi"), ("email_address", "thandi@example.co.za"),
             ("merchant_id", "10000100"), *extra]
    return pairs + [("signature", payfast.signature(pairs, passphrase))]


def notify(client, pairs):
    return client.post("/api/payments/payfast/notify", content=urlencode(pairs),
                       headers={"Content-Type": "application/x-www-form-urlencoded"})


def test_valid_notification_marks_order_paid(client, db, pending):
    r = notify(client, itn(pending["payment"]))
    assert r.status_code == 200 and r.text == "applied"
    order = db.get(Order, pending["order"]["id"])
    assert order.paid_cents == order.total_cents
    db.refresh(pending["payment"])
    assert pending["payment"].status == PaymentStatus.PAID
    assert pending["payment"].provider_payment_id == "1234567"
    # Same notification again (PayFast retries): counted once
    assert notify(client, itn(pending["payment"])).text == "duplicate"
    assert db.get(Order, pending["order"]["id"]).paid_cents == order.total_cents


def test_forged_signature_rejected(client, db, pending):
    r = notify(client, itn(pending["payment"], passphrase="attacker-guess"))
    assert r.status_code == 400
    assert db.get(Order, pending["order"]["id"]).paid_cents == 0
    event = db.scalar(select(PaymentEvent).where(PaymentEvent.outcome == "bad_signature"))
    assert event.signature_valid is False


def test_notification_from_elsewhere_rejected(client, db, pending, monkeypatch):
    monkeypatch.setattr(payfast, "_resolve_hosts", lambda: {"197.97.145.144"})  # not this caller
    assert notify(client, itn(pending["payment"])).status_code == 400
    assert db.scalar(select(AuditLog).where(AuditLog.action == "payment.payfast_bad_source"))
    assert db.get(Order, pending["order"]["id"]).paid_cents == 0


def test_payfast_must_confirm(client, db, pending, monkeypatch):
    sent = []
    monkeypatch.setattr(payfast, "_confirm_with_payfast", lambda body: sent.append(body) or False)
    assert notify(client, itn(pending["payment"])).status_code == 400
    assert sent and sent[0].startswith(f"m_payment_id={pending['payment'].reference}")
    assert "signature=" not in sent[0]
    assert db.get(Order, pending["order"]["id"]).paid_cents == 0


def test_wrong_amount_never_marks_paid(client, db, pending):
    r = notify(client, itn(pending["payment"], amount="1.00"))
    assert r.status_code == 200 and r.text == "amount_mismatch"
    assert db.get(Order, pending["order"]["id"]).paid_cents == 0


def test_wrong_merchant_rejected(client, pending):
    pairs = [(k, "99999" if k == "merchant_id" else v) for k, v in itn(pending["payment"])[:-1]]
    pairs.append(("signature", payfast.signature(pairs, PASS)))
    assert notify(client, pairs).status_code == 400


@pytest.mark.parametrize("pf_status,ours", [("FAILED", PaymentStatus.FAILED),
                                            ("CANCELLED", PaymentStatus.CANCELLED)])
def test_failed_and_cancelled(client, db, pending, pf_status, ours):
    r = notify(client, itn(pending["payment"], status=pf_status))
    assert r.status_code == 200
    db.refresh(pending["payment"])
    assert pending["payment"].status == ours
    assert db.get(Order, pending["order"]["id"]).paid_cents == 0


def test_endpoint_off_unless_payfast_is_the_provider(client, monkeypatch):
    monkeypatch.setattr(settings, "payment_provider", "sandbox")
    assert notify(client, [("m_payment_id", "x")]).status_code == 404
