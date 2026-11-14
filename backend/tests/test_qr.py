"""Order QR codes (SEC-010 – SEC-012, UAT-008)."""

import re

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.models.enums import BusinessStaffRole as S
from app.models.enums import UserRole
from tests.conftest import auth_header
from tests.test_orders import LAUNDRY, order_body, place

CODE_RE = re.compile(r"^LCQ1\.LC-[0-9A-HJKMNP-TV-Z]{8}\.\d+\.[0-9A-HJKMNP-TV-Z]{16}$")


@pytest.fixture
def customer(make_user):
    return make_user(UserRole.CUSTOMER)


@pytest.fixture
def laundry(make_laundry):
    return make_laundry(*LAUNDRY)


@pytest.fixture
def order(client, customer, laundry):
    return place(client, customer, order_body(laundry)).json()


def code_of(client, user, order):
    r = client.get(f"/api/business/orders/{order['id']}/qr?format=text", headers=auth_header(user))
    assert r.status_code == 200, r.text
    return r.json()["code"]


def scan(client, user, code, expected=None):
    body = {"code": code} | ({"expected_order_id": expected} if expected else {})
    return client.post("/api/scan", headers=auth_header(user), json=body)


def last_rejection(db):
    return db.scalars(select(AuditLog).where(AuditLog.action == "qr.scan_rejected")
                      .order_by(AuditLog.id.desc())).first()


# ---------- Generating ----------

def test_code_format_is_compact_and_scannable(client, laundry, order):
    code = code_of(client, laundry.owner, order)
    assert CODE_RE.match(code)
    assert order["order_number"] in code


def test_png_and_svg_labels(client, laundry, order):
    h = auth_header(laundry.owner)
    png = client.get(f"/api/business/orders/{order['id']}/qr", headers=h)
    assert png.status_code == 200
    assert png.headers["content-type"] == "image/png"
    assert png.content.startswith(b"\x89PNG")
    svg = client.get(f"/api/business/orders/{order['id']}/qr?format=svg", headers=h)
    assert svg.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in svg.content


def test_customer_gets_same_code_for_own_order(client, customer, laundry, order):
    mine = client.get(f"/api/orders/{order['id']}/qr?format=text", headers=auth_header(customer))
    assert mine.json()["code"] == code_of(client, laundry.owner, order)


def test_others_cannot_get_the_code(client, make_user, make_laundry, order):
    other_customer = make_user(UserRole.CUSTOMER)
    other_laundry = make_laundry()
    assert client.get(f"/api/orders/{order['id']}/qr",
                      headers=auth_header(other_customer)).status_code == 404
    assert client.get(f"/api/business/orders/{order['id']}/qr",
                      headers=auth_header(other_laundry.owner)).status_code == 404


# ---------- Scanning ----------

def test_attendant_scans_valid_code(client, laundry, add_staff, customer, order, db):
    attendant = add_staff(laundry, S.ATTENDANT)
    r = scan(client, attendant, code_of(client, laundry.owner, order))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid"] is True
    assert body["order_number"] == order["order_number"]
    assert body["customer_name"] == customer.full_name
    assert body["item_count"] == 1

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "qr.scanned"))
    assert entry.actor_user_id == attendant.id
    assert entry.entity_id == order["id"]


def test_scan_is_forgiving_of_case_and_spaces(client, laundry, order):
    code = code_of(client, laundry.owner, order)
    assert scan(client, laundry.owner, f"  {code.lower()} ").status_code == 200


@pytest.mark.parametrize("make_bad,problem", [
    (lambda c: c[:-1] + ("A" if c[-1] != "A" else "B"), "bad_signature"),  # signature edited
    (lambda c: "hello world", "malformed"),
    (lambda c: "https://evil.example/LCQ1", "malformed"),
    (lambda c: c.replace("LCQ1", "LCQ2"), "malformed"),
])
def test_invalid_codes_rejected_and_logged(client, laundry, order, db, make_bad, problem):
    bad = make_bad(code_of(client, laundry.owner, order))
    r = scan(client, laundry.owner, bad)
    assert r.status_code == 422
    assert r.json()["detail"]["valid"] is False
    assert r.json()["detail"]["problem"] == problem
    assert last_rejection(db).details["problem"] == problem


def test_swapping_the_order_number_is_detected(client, customer, laundry, order):
    # Take a genuine code and put another (real) order's number in it
    other = place(client, customer, order_body(laundry)).json()
    code = code_of(client, laundry.owner, order)
    forged = code.replace(order["order_number"], other["order_number"])
    r = scan(client, laundry.owner, forged)
    assert r.status_code == 422
    assert r.json()["detail"]["problem"] == "bad_signature"


def test_code_from_another_laundry_is_a_mismatch(client, customer, make_laundry, laundry, order, db):
    other = make_laundry()
    theirs = place(client, customer, order_body(other)).json()
    r = scan(client, laundry.owner, code_of(client, other.owner, theirs))
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["problem"] == "wrong_business"
    assert theirs["order_number"] not in str(detail)  # nothing about the other order leaks
    assert last_rejection(db).entity_id == theirs["id"]


def test_wrong_bag_for_expected_order(client, customer, laundry, order):
    other = place(client, customer, order_body(laundry)).json()
    code = code_of(client, laundry.owner, other)
    assert scan(client, laundry.owner, code, expected=order["id"]).status_code == 409
    assert scan(client, laundry.owner, code, expected=other["id"]).status_code == 200


# ---------- Reissuing ----------

def test_reissue_invalidates_old_label(client, laundry, add_staff, order, db):
    manager = add_staff(laundry, S.MANAGER)
    old = code_of(client, laundry.owner, order)
    r = client.post(f"/api/business/orders/{order['id']}/qr/reissue", headers=auth_header(manager))
    assert r.status_code == 200
    new = r.json()["code"]
    assert new != old and ".2." in new

    rejected = scan(client, laundry.owner, old)
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["problem"] == "replaced"
    assert scan(client, laundry.owner, new).status_code == 200
    assert db.scalar(select(AuditLog).where(AuditLog.action == "qr.reissued"))


def test_attendant_cannot_reissue(client, laundry, add_staff, order):
    attendant = add_staff(laundry, S.ATTENDANT)
    r = client.post(f"/api/business/orders/{order['id']}/qr/reissue",
                    headers=auth_header(attendant))
    assert r.status_code == 403


# ---------- Who can scan ----------

@pytest.mark.parametrize("role", [UserRole.CUSTOMER, UserRole.DRIVER, UserRole.ADMIN])
def test_only_business_staff_can_scan_for_now(client, make_user, laundry, order, role):
    code = code_of(client, laundry.owner, order)
    assert scan(client, make_user(role), code).status_code == 403
