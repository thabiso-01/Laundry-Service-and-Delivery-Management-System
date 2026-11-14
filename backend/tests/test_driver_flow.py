"""Drivers, one-time codes and verified handovers
(UR-009, SEC-004 – SEC-017, SEC-022, Business Rule 7, UAT-006 – UAT-011)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog, DeliveryJob, HandoverRecord, Order, OrderOtp
from app.models.enums import JobKind, JobStatus, UserRole, VehicleType
from app.models.enums import VerificationStatus as V
from tests.conftest import auth_header, pay
from tests.test_orders import HOME, LAUNDRY, order_body, place

AT_HOME = {"latitude": HOME["latitude"], "longitude": HOME["longitude"]}
AT_LAUNDRY = {"latitude": LAUNDRY[0], "longitude": LAUNDRY[1]}
SANDTON = {"latitude": -26.1076, "longitude": 28.0567}


# ---------- Fixtures and helpers ----------

@pytest.fixture
def customer(make_user):
    return make_user(UserRole.CUSTOMER, phone="+27821110000")


@pytest.fixture
def laundry(make_laundry):
    return make_laundry(*LAUNDRY)


@pytest.fixture
def online_driver(client, make_driver, db):
    def _make():
        d = make_driver(V.APPROVED)
        d.full_name = "Sipho Ndlovu"
        d.phone = f"+2783{d.id.int % 10_000_000:07d}"
        d.driver_profile.vehicle_type = VehicleType.MOTORCYCLE
        d.driver_profile.vehicle_registration = "GP 123-456"
        db.flush()
        r = client.patch("/api/driver/availability", headers=auth_header(d),
                         json={"is_available": True})
        assert r.status_code == 200, r.text
        return d
    return _make


@pytest.fixture
def driver(online_driver):
    return online_driver()


@pytest.fixture
def accepted_order(client, customer, laundry):
    o = place(client, customer, order_body(laundry)).json()
    pay(client, customer, o)
    r = client.post(f"/api/business/orders/{o['id']}/accept", headers=auth_header(laundry.owner))
    assert r.status_code == 200, r.text
    return o


def board(client, driver, where=AT_HOME, **params):
    return client.get("/api/driver/jobs/available", headers=auth_header(driver),
                      params={"lat": where["latitude"], "lng": where["longitude"]} | params)


def job_of(db, order, kind):
    return db.scalar(select(DeliveryJob).where(DeliveryJob.order_id == order["id"],
                                               DeliveryJob.kind == kind))


def take(client, driver, job):
    r = client.post(f"/api/driver/jobs/{job.id}/accept", headers=auth_header(driver))
    assert r.status_code == 200, r.text
    return r.json()


def customer_code(client, customer, order):
    r = client.get(f"/api/orders/{order['id']}/otp", headers=auth_header(customer))
    assert r.status_code == 200, r.text
    return r.json()["code"]


def qr_code(client, laundry, order):
    return client.get(f"/api/business/orders/{order['id']}/qr?format=text",
                      headers=auth_header(laundry.owner)).json()["code"]


def new_seal():
    """Seal numbers are unique platform-wide, so every test bag gets a fresh one."""
    return "S" + uuid.uuid4().hex[:10].upper()


def collect(client, driver, job, code, where=AT_HOME, seals=None):
    return client.post(f"/api/driver/jobs/{job.id}/collect", headers=auth_header(driver),
                       json={"otp": code, "seal_numbers": seals or [new_seal()], **where})


def recorded_seals(client, laundry, order, leg="collection"):
    seals = client.get(f"/api/business/orders/{order['id']}",
                       headers=auth_header(laundry.owner)).json()["seals"]
    return [s["seal_number"] for s in seals if s["leg"] == leg]


def receive(client, laundry, order, code, seals=None, intact=True):
    if seals is None:
        seals = recorded_seals(client, laundry, order)
    return client.post(f"/api/business/orders/{order['id']}/receive",
                       headers=auth_header(laundry.owner),
                       json={"code": code, "seal_numbers": seals, "seals_intact": intact})


def wrong(code):
    return f"{(int(code) + 1) % 1_000_000:06d}"


def collected_and_received(client, db, customer, laundry, driver, order):
    job = job_of(db, order, JobKind.COLLECTION)
    take(client, driver, job)
    assert collect(client, driver, job, customer_code(client, customer, order)).status_code == 200
    assert receive(client, laundry, order, qr_code(client, laundry, order)).status_code == 200


def weigh_as_estimated(client, laundry, order):
    detail = client.get(f"/api/business/orders/{order['id']}", headers=auth_header(laundry.owner))
    lines = [{"service_id": i["service_id"], "actual_quantity": i["quantity"]}
             for i in detail.json()["items"] if i["pricing_unit"] == "per_kg"]
    if lines:
        r = client.post(f"/api/business/orders/{order['id']}/weigh",
                        headers=auth_header(laundry.owner), json={"lines": lines})
        assert r.status_code == 200, r.text


def make_ready(client, laundry, order):
    weigh_as_estimated(client, laundry, order)
    h = auth_header(laundry.owner)
    for s in ("processing", "ready"):
        r = client.post(f"/api/business/orders/{order['id']}/status", headers=h, json={"status": s})
        assert r.status_code == 200, r.text


# ---------- The whole journey (UAT-006 – UAT-011) ----------

def test_full_order_journey(client, db, customer, laundry, online_driver, accepted_order):
    o = accepted_order
    collector, deliverer = online_driver(), online_driver()

    # Collection job is on the board; collector takes it (UAT-006)
    items = board(client, collector).json()
    assert [i["kind"] for i in items] == ["collection"]
    take(client, collector, job_of(db, o, JobKind.COLLECTION))
    mine = client.get(f"/api/orders/{o['id']}", headers=auth_header(customer)).json()
    assert mine["driver"]["first_name"] == "Sipho"
    assert mine["driver"]["vehicle_registration"] == "GP 123-456"

    # Customer → driver with the collection OTP (UAT-007)
    job = job_of(db, o, JobKind.COLLECTION)
    r = collect(client, collector, job, customer_code(client, customer, o))
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "customer_to_driver"
    assert r.json()["location_flagged"] is False

    # Driver → laundry: staff scan the bag (UAT-008)
    r = receive(client, laundry, o, qr_code(client, laundry, o))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "received"
    assert job_of(db, o, JobKind.COLLECTION).status == JobStatus.COMPLETED

    # Laundry cleans it; delivery job appears
    make_ready(client, laundry, o)
    items = board(client, deliverer, AT_LAUNDRY).json()
    assert [i["kind"] for i in items] == ["delivery"]
    delivery = job_of(db, o, JobKind.DELIVERY)
    take(client, deliverer, delivery)

    # Laundry → driver: driver scans the bag
    r = client.post(f"/api/driver/jobs/{delivery.id}/pickup", headers=auth_header(deliverer),
                    json={"code": qr_code(client, laundry, o), "seal_numbers": [new_seal()],
                          **AT_LAUNDRY})
    assert r.status_code == 200, r.text

    # Driver → customer with a *different* delivery OTP (UAT-011)
    delivery_code = customer_code(client, customer, o)
    r = client.post(f"/api/driver/jobs/{delivery.id}/deliver", headers=auth_header(deliverer),
                    json={"otp": delivery_code, "seals_intact": True, **AT_HOME})
    assert r.status_code == 200, r.text

    # Everything recorded (UAT-009, SEC-013 – SEC-017)
    final = client.get(f"/api/orders/{o['id']}", headers=auth_header(customer)).json()
    assert final["status"] == "delivered"
    assert final["driver"] is None
    assert [e["to_status"] for e in final["history"]] == [
        "placed", "accepted", "collected", "received", "processing", "ready",
        "out_for_delivery", "delivered"]
    assert [(h["kind"], h["method"]) for h in final["handovers"]] == [
        ("customer_to_driver", "otp"), ("driver_to_business", "qr"),
        ("business_to_driver", "qr"), ("driver_to_customer", "otp")]

    records = db.scalars(select(HandoverRecord).where(HandoverRecord.order_id == o["id"])
                         .order_by(HandoverRecord.created_at)).all()
    assert [(r.from_user_id, r.to_user_id) for r in records] == [
        (customer.id, collector.id), (collector.id, laundry.owner.id),
        (None, deliverer.id), (deliverer.id, customer.id)]
    actions = set(db.scalars(select(AuditLog.action)).all())
    assert {"handover.customer_to_driver", "handover.driver_to_business",
            "handover.business_to_driver", "handover.driver_to_customer"} <= actions


def test_driver_fees_come_from_delivery_fee(db, accepted_order):
    order = db.get(Order, accepted_order["id"])
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    assert 0 < job.driver_fee_cents < order.delivery_fee_cents / 2


# ---------- Job board ----------

def test_board_shows_no_personal_details(client, customer, driver, accepted_order):
    r = board(client, driver)
    assert r.status_code == 200
    item = r.json()[0]
    assert item["pickup_area"] == "Marshalltown, Johannesburg"
    for secret in (customer.full_name, customer.phone, HOME["address_line"], customer.email):
        assert secret not in r.text


def test_board_respects_radius(client, driver, accepted_order):
    far_away = {"latitude": -25.7479, "longitude": 28.2293}  # Pretoria
    assert board(client, driver, far_away).json() == []


def test_pending_driver_cannot_work(client, make_driver, accepted_order, db):
    pending = make_driver(V.PENDING)
    h = auth_header(pending)
    assert client.patch("/api/driver/availability", headers=h,
                        json={"is_available": True}).status_code == 403
    assert board(client, pending).status_code == 403
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    assert client.post(f"/api/driver/jobs/{job.id}/accept", headers=h).status_code == 403


def test_offline_driver_sees_no_jobs(client, driver, accepted_order, db):
    client.patch("/api/driver/availability", headers=auth_header(driver),
                 json={"is_available": False})
    assert board(client, driver).status_code == 409
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    assert client.post(f"/api/driver/jobs/{job.id}/accept",
                       headers=auth_header(driver)).status_code == 409


def test_only_one_driver_wins_a_job(client, online_driver, accepted_order, db):
    first, second = online_driver(), online_driver()
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    assert client.post(f"/api/driver/jobs/{job.id}/accept",
                       headers=auth_header(first)).status_code == 200
    r = client.post(f"/api/driver/jobs/{job.id}/accept", headers=auth_header(second))
    assert r.status_code == 409
    assert board(client, second).json() == []


def test_driver_limit_on_active_jobs(client, customer, laundry, driver, db):
    jobs = []
    for _ in range(4):
        o = place(client, customer, order_body(laundry)).json()
        pay(client, customer, o)
        client.post(f"/api/business/orders/{o['id']}/accept", headers=auth_header(laundry.owner))
        jobs.append(job_of(db, o, JobKind.COLLECTION))
    for job in jobs[:3]:
        take(client, driver, job)
    r = client.post(f"/api/driver/jobs/{jobs[3].id}/accept", headers=auth_header(driver))
    assert r.status_code == 409
    assert "3 active jobs" in r.json()["detail"]


def test_cannot_touch_another_drivers_job(client, online_driver, customer, accepted_order, db):
    owner, intruder = online_driver(), online_driver()
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, owner, job)
    code = customer_code(client, customer, accepted_order)
    assert collect(client, intruder, job, code).status_code == 404
    assert client.get(f"/api/driver/jobs/{job.id}",
                      headers=auth_header(intruder)).status_code == 404


def test_assigned_driver_gets_contact_details_until_done(client, customer, driver,
                                                         accepted_order, db):
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    details = take(client, driver, job)
    assert details["pickup"]["phone"] == customer.phone
    assert details["pickup"]["address_line"] == HOME["address_line"]
    assert details["pickup"]["name"] == customer.full_name.split()[0]  # first name only
    assert details["next_step"].startswith("Collect from customer")

    job.status = JobStatus.COMPLETED  # pretend it's finished
    db.flush()
    after = client.get(f"/api/driver/jobs/{job.id}", headers=auth_header(driver)).json()
    assert after["pickup"]["phone"] is None
    assert after["pickup"]["address_line"] is None


def test_release_puts_job_back_on_board(client, online_driver, accepted_order, db):
    first, second = online_driver(), online_driver()
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, first, job)
    r = client.post(f"/api/driver/jobs/{job.id}/release", headers=auth_header(first),
                    json={"reason": "Car broke down"})
    assert r.status_code == 200
    assert [i["id"] for i in board(client, second).json()] == [str(job.id)]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "job.released"))


def test_cannot_release_after_pickup(client, customer, driver, accepted_order, db):
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    collect(client, driver, job, customer_code(client, customer, accepted_order))
    r = client.post(f"/api/driver/jobs/{job.id}/release", headers=auth_header(driver),
                    json={"reason": "Changed my mind"})
    assert r.status_code == 409


def test_revoking_driver_releases_their_jobs(client, make_user, driver, accepted_order, db):
    admin = make_user(UserRole.ADMIN)
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    r = client.post(f"/api/admin/drivers/{driver.id}/reject", headers=auth_header(admin),
                    json={"reason": "Complaint under investigation"})
    assert r.status_code == 200
    db.refresh(job)
    assert job.status == JobStatus.OPEN and job.driver_id is None


def test_customer_cancel_cancels_job_and_code(client, customer, driver, accepted_order, db):
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    client.post(f"/api/orders/{accepted_order['id']}/cancel", headers=auth_header(customer))
    db.refresh(job)
    assert job.status == JobStatus.CANCELLED
    live = db.scalars(select(OrderOtp).where(OrderOtp.order_id == accepted_order["id"],
                                             OrderOtp.revoked_at.is_(None),
                                             OrderOtp.used_at.is_(None))).all()
    assert live == []


# ---------- One-time codes (SEC-005 – SEC-008) ----------

def test_wrong_code_is_counted_and_locks(client, customer, driver, accepted_order, db):
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    code = customer_code(client, customer, accepted_order)

    for attempt in range(1, 5):
        r = collect(client, driver, job, wrong(code))
        assert r.status_code == 400
        assert f"{5 - attempt} attempt(s) left" in r.json()["detail"]
    assert collect(client, driver, job, wrong(code)).status_code == 423
    # Even the right code is refused once locked
    assert collect(client, driver, job, code).status_code == 423
    assert len(db.scalars(select(AuditLog).where(AuditLog.action == "otp.failed")).all()) == 5

    # Customer makes a new code; the old one is dead, the new one works
    fresh = client.post(f"/api/orders/{accepted_order['id']}/otp/regenerate",
                        headers=auth_header(customer)).json()["code"]
    assert fresh != code
    assert collect(client, driver, job, code).status_code == 400
    assert collect(client, driver, job, fresh).status_code == 200


def test_expired_code_rejected(client, customer, driver, accepted_order, db):
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    code = customer_code(client, customer, accepted_order)
    otp_row = db.scalar(select(OrderOtp).where(OrderOtp.order_id == accepted_order["id"]))
    otp_row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.flush()
    r = collect(client, driver, job, code)
    assert r.status_code == 409
    assert "expired" in r.json()["detail"]


def test_collection_and_delivery_codes_differ_and_cannot_be_reused(
        client, db, customer, laundry, online_driver, accepted_order):
    o = accepted_order
    collector, deliverer = online_driver(), online_driver()
    collection_code = customer_code(client, customer, o)
    collected_and_received(client, db, customer, laundry, collector, o)
    make_ready(client, laundry, o)
    delivery = job_of(db, o, JobKind.DELIVERY)
    take(client, deliverer, delivery)
    client.post(f"/api/driver/jobs/{delivery.id}/pickup", headers=auth_header(deliverer),
                json={"code": qr_code(client, laundry, o), "seal_numbers": [new_seal()],
                          **AT_LAUNDRY})

    delivery_code = customer_code(client, customer, o)
    assert delivery_code != collection_code
    # The used collection code can't complete the delivery (SEC-008)
    r = client.post(f"/api/driver/jobs/{delivery.id}/deliver", headers=auth_header(deliverer),
                    json={"otp": collection_code, "seals_intact": True, **AT_HOME})
    assert r.status_code == 400


def test_no_code_shown_when_none_needed(client, customer, laundry):
    o = place(client, customer, order_body(laundry)).json()  # not accepted yet
    r = client.get(f"/api/orders/{o['id']}/otp", headers=auth_header(customer))
    assert r.status_code == 404


def test_codes_are_not_stored():
    columns = {c.name for c in OrderOtp.__table__.columns}
    assert not {"code", "otp", "code_hash"} & columns


# ---------- QR at the laundry ----------

def test_receive_requires_the_right_bag(client, db, customer, laundry, driver, accepted_order):
    other = place(client, customer, order_body(laundry)).json()
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    collect(client, driver, job, customer_code(client, customer, accepted_order))

    r = receive(client, laundry, accepted_order, qr_code(client, laundry, other))
    assert r.status_code == 422
    assert r.json()["detail"]["problem"] == "not_expected_order"
    assert receive(client, laundry, accepted_order, "garbage").status_code == 422
    assert receive(client, laundry, accepted_order,
                   qr_code(client, laundry, accepted_order)).status_code == 200


def test_cannot_receive_before_collection(client, laundry, accepted_order):
    r = receive(client, laundry, accepted_order, qr_code(client, laundry, accepted_order))
    assert r.status_code == 409


# ---------- GPS (SEC-022) ----------

def test_handover_far_from_address_is_flagged(client, customer, driver, accepted_order, db):
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    r = collect(client, driver, job, customer_code(client, customer, accepted_order), SANDTON)
    assert r.status_code == 200  # not blocked – GPS can be wrong – but flagged
    assert r.json()["location_flagged"] is True
    assert r.json()["distance_from_expected_m"] > 10_000


def test_handover_records_are_permanent(client, customer, driver, accepted_order, db):
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    collect(client, driver, job, customer_code(client, customer, accepted_order))
    for sql in ("UPDATE handover_records SET location_flagged = false",
                "DELETE FROM handover_records"):
        sp = db.begin_nested()
        with pytest.raises(DBAPIError):
            db.execute(text(sql))
        sp.rollback()
