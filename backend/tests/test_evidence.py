"""Seals, photo evidence, incidents and suspension
(SEC-025 – SEC-037, SEC-044, SEC-048, UR-015, UAT-012, UAT-013)."""

import re
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog, BagSeal, DeliveryJob, EvidencePhoto, Incident
from app.models.enums import (
    AccountStatus,
    IncidentCategory,
    IncidentSeverity,
    JobKind,
    JobStatus,
    SealCheck,
    UserRole,
)
from tests.conftest import auth_header, pay
from tests.test_driver_flow import (  # noqa: F401 (fixtures are used by name)
    AT_HOME,
    AT_LAUNDRY,
    accepted_order,
    collect,
    customer,
    customer_code,
    driver,
    job_of,
    laundry,
    make_ready,
    new_seal,
    online_driver,
    qr_code,
    receive,
    recorded_seals,
    take,
)
from tests.test_orders import order_body, place

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
PDF = b"%PDF-1.7\n" + b"0" * 200


@pytest.fixture
def admin(make_user):
    return make_user(UserRole.ADMIN)


@pytest.fixture
def collected(client, db, customer, driver, accepted_order):
    """An order the driver has just collected, with one seal."""
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    seal = new_seal()
    r = collect(client, driver, job, customer_code(client, customer, accepted_order),
                seals=[seal])
    assert r.status_code == 200, r.text
    return {"order": accepted_order, "job": job, "seal": seal}


def upload_photo(client, user, stage, *, order=None, incident=None, content=PNG):
    data = {"stage": stage}
    if order:
        data["order_id"] = order["id"]
    if incident:
        data["incident_id"] = incident["id"]
    return client.post("/api/photos", headers=auth_header(user), data=data,
                       files={"file": ("photo.png", content, "image/png")})


def report(client, user, category="missing_items", order=None, description=None):
    body = {"category": category,
            "description": description or "Two school shirts were not returned."}
    if order:
        body["order_id"] = order["id"]
    return client.post("/api/incidents", headers=auth_header(user), json=body)


# ======================= Seals (SEC-025 – SEC-028) =======================

def test_seals_recorded_at_collection_are_visible(client, customer, collected):
    o = client.get(f"/api/orders/{collected['order']['id']}", headers=auth_header(customer)).json()
    assert [(s["seal_number"], s["leg"], s["check_result"]) for s in o["seals"]] == [
        (collected["seal"], "collection", None)]


def test_reused_seal_refused_without_using_up_code(client, db, customer, laundry, driver,
                                                   collected, accepted_order):
    # A second order, and the driver tries to reuse the first bag's seal
    o2 = place(client, customer, order_body(laundry)).json()
    pay(client, customer, o2)
    client.post(f"/api/business/orders/{o2['id']}/accept", headers=auth_header(laundry.owner))
    job2 = job_of(db, o2, JobKind.COLLECTION)
    take(client, driver, job2)
    code = customer_code(client, customer, o2)

    r = collect(client, driver, job2, code, seals=[collected["seal"]])
    assert r.status_code == 409
    assert "already been used" in r.json()["detail"]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "seal.reuse_attempt"))
    # The customer's code still works with a fresh seal
    assert collect(client, driver, job2, code, seals=[new_seal()]).status_code == 200


@pytest.mark.parametrize("seals", [[], ["ab"], ["GOOD-1234", "GOOD-1234"], ["BAD SEAL!!"]],
                         ids=["none", "too-short", "duplicate", "bad-characters"])
def test_invalid_seal_numbers_rejected(client, db, customer, driver, accepted_order, seals):
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    r = client.post(f"/api/driver/jobs/{job.id}/collect", headers=auth_header(driver),
                    json={"otp": customer_code(client, customer, accepted_order),
                          "seal_numbers": seals, **AT_HOME})
    assert r.status_code == 422


def test_seals_match_on_receipt(client, db, laundry, collected):
    r = receive(client, laundry, collected["order"], qr_code(client, laundry, collected["order"]))
    assert r.status_code == 200
    assert r.json()["seal_incident_reference"] is None
    seal = db.scalar(select(BagSeal).where(BagSeal.seal_number == collected["seal"]))
    assert seal.check_result == SealCheck.INTACT
    assert seal.checked_by_id == laundry.owner.id


def test_broken_seal_opens_incident_but_handover_completes(client, db, laundry, collected):
    o = collected["order"]
    r = receive(client, laundry, o, qr_code(client, laundry, o), intact=False)
    assert r.status_code == 200
    assert r.json()["status"] == "received"
    ref = r.json()["seal_incident_reference"]
    assert re.fullmatch(r"INC-[0-9A-HJKMNP-TV-Z]{8}", ref)

    incident = db.scalar(select(Incident).where(Incident.reference == ref))
    assert incident.category == IncidentCategory.BROKEN_SEAL
    assert incident.severity == IncidentSeverity.HIGH
    assert incident.is_automatic is True
    assert db.scalar(select(BagSeal.check_result).where(
        BagSeal.seal_number == collected["seal"])) == SealCheck.BROKEN


def test_missing_or_swapped_seal_is_a_mismatch(client, db, laundry, collected):
    o = collected["order"]
    r = receive(client, laundry, o, qr_code(client, laundry, o), seals=["SWAPPED-999"])
    incident = db.scalar(select(Incident).where(
        Incident.reference == r.json()["seal_incident_reference"]))
    assert incident.category == IncidentCategory.SEAL_MISMATCH
    assert collected["seal"] in incident.description
    assert "SWAPPED-999" in incident.description
    assert db.scalar(select(BagSeal.check_result).where(
        BagSeal.seal_number == collected["seal"])) == SealCheck.MISSING


def test_broken_seal_at_delivery_opens_incident(client, db, customer, laundry, online_driver,
                                                collected):
    o = collected["order"]
    receive(client, laundry, o, qr_code(client, laundry, o))
    make_ready(client, laundry, o)
    deliverer = online_driver()
    delivery = job_of(db, o, JobKind.DELIVERY)
    take(client, deliverer, delivery)
    client.post(f"/api/driver/jobs/{delivery.id}/pickup", headers=auth_header(deliverer),
                json={"code": qr_code(client, laundry, o), "seal_numbers": [new_seal()],
                      **AT_LAUNDRY})
    r = client.post(f"/api/driver/jobs/{delivery.id}/deliver", headers=auth_header(deliverer),
                    json={"otp": customer_code(client, customer, o), "seals_intact": False,
                          **AT_HOME})
    assert r.status_code == 200
    assert r.json()["incident_reference"].startswith("INC-")
    assert recorded_seals(client, laundry, o, "delivery")


# ======================= Photos (SEC-029 – SEC-032) =======================

def test_driver_photo_at_collection_visible_to_parties(client, db, customer, driver, admin,
                                                       make_user, collected):
    o = collected["order"]
    r = upload_photo(client, driver, "collection", order=o)
    assert r.status_code == 201, r.text
    photo = r.json()
    assert photo["stage"] == "collection" and photo["uploader_role"] == "driver"
    assert db.get(EvidencePhoto, photo["id"]).job_id == collected["job"].id  # SEC-032

    listed = client.get("/api/photos", params={"order_id": o["id"]}, headers=auth_header(customer))
    assert [p["id"] for p in listed.json()] == [photo["id"]]
    assert client.get(f"/api/photos/{photo['id']}/file",
                      headers=auth_header(customer)).content == PNG

    stranger = make_user(UserRole.CUSTOMER)
    assert client.get(f"/api/photos/{photo['id']}/file",
                      headers=auth_header(stranger)).status_code == 404
    assert client.get("/api/photos", params={"order_id": o["id"]},
                      headers=auth_header(stranger)).status_code == 404

    client.get(f"/api/photos/{photo['id']}/file", headers=auth_header(admin))
    viewed = db.scalar(select(AuditLog).where(AuditLog.action == "photo.viewed",
                                              AuditLog.actor_user_id == admin.id))
    assert viewed is not None


def test_photo_stage_rules(client, customer, driver, laundry, make_user, collected):
    o = collected["order"]
    assert upload_photo(client, driver, "receipt", order=o).status_code == 403   # laundry's stage
    assert upload_photo(client, laundry.owner, "receipt", order=o).status_code == 201
    assert upload_photo(client, customer, "delivery", order=o).status_code == 403  # use a report
    other_driver = make_user(UserRole.DRIVER)
    assert upload_photo(client, other_driver, "collection", order=o).status_code in (403, 404)


def test_driver_cannot_add_photos_after_job_is_done(client, laundry, driver, collected):
    o = collected["order"]
    receive(client, laundry, o, qr_code(client, laundry, o))
    assert upload_photo(client, driver, "collection", order=o).status_code == 403


def test_photos_must_be_images(client, driver, collected):
    r = upload_photo(client, driver, "collection", order=collected["order"], content=PDF)
    assert r.status_code == 415


def test_tampered_photo_detected(client, db, driver, admin, collected, isolated_uploads):
    photo = upload_photo(client, driver, "collection", order=collected["order"]).json()
    path = db.get(EvidencePhoto, photo["id"]).file_path
    Path(isolated_uploads / path).write_bytes(PNG + b"edited")
    r = client.get(f"/api/photos/{photo['id']}/file", headers=auth_header(admin))
    assert r.status_code == 409
    assert db.scalar(select(AuditLog).where(AuditLog.action == "photo.integrity_failed"))


def test_photo_records_are_permanent(client, db, driver, collected):
    upload_photo(client, driver, "collection", order=collected["order"])
    sp = db.begin_nested()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM evidence_photos"))
    sp.rollback()


# ======================= Incidents (SEC-033 – SEC-037) =======================

def test_customer_reports_missing_items(client, db, customer, accepted_order):
    r = report(client, customer, order=accepted_order)
    assert r.status_code == 201, r.text
    body = r.json()
    assert re.fullmatch(r"INC-[0-9A-HJKMNP-TV-Z]{8}", body["reference"])  # SEC-035
    assert body["status"] == "open"
    assert body["order_number"] == accepted_order["order_number"]
    assert body["updates"][0]["to_status"] == "open"

    mine = client.get("/api/incidents", headers=auth_header(customer)).json()
    assert [i["reference"] for i in mine["items"]] == [body["reference"]]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "incident.opened"))


def test_reports_only_about_your_own_orders(client, make_user, accepted_order):
    stranger = make_user(UserRole.CUSTOMER)
    assert report(client, stranger, order=accepted_order).status_code == 404


def test_report_without_order_only_for_general_categories(client, make_user):
    user = make_user(UserRole.CUSTOMER)
    assert report(client, user, "missing_items").status_code == 422
    r = report(client, user, "fraud",
               description="Someone phoned pretending to be a LaundryConnect driver.")
    assert r.status_code == 201  # SEC-048


def test_driver_and_business_can_report_security_incidents(client, laundry, driver, collected):
    o = collected["order"]
    assert report(client, driver, "security", order=o,
                  description="Customer's dog bit me at the gate.").status_code == 201
    assert report(client, laundry.owner, "damaged_items", order=o,
                  description="Bag arrived soaking wet.").status_code == 201


def test_other_reporters_cannot_see_my_report(client, make_user, customer, accepted_order):
    ref = report(client, customer, order=accepted_order).json()
    stranger = make_user(UserRole.CUSTOMER)
    assert client.get(f"/api/incidents/{ref['id']}", headers=auth_header(stranger)).status_code == 404


def test_full_investigation(client, db, customer, laundry, driver, admin, collected):
    """UAT-013: an administrator can investigate and resolve a reported incident."""
    o = collected["order"]
    # Driver photographs the bag while the job is still theirs, then drops it off
    assert upload_photo(client, driver, "collection", order=o).status_code == 201
    receive(client, laundry, o, qr_code(client, laundry, o))
    inc = report(client, customer, order=o).json()
    upload_photo(client, customer, "incident", incident=inc)
    h = auth_header(admin)

    case = client.get(f"/api/admin/incidents/{inc['id']}", headers=h).json()
    ev = case["evidence"]
    assert [x["kind"] for x in ev["handovers"]] == ["customer_to_driver", "driver_to_business"]
    assert ev["handovers"][0]["latitude"] == AT_HOME["latitude"]  # SEC-023: route evidence
    assert ev["seals"][0]["check_result"] == "intact"
    assert len(ev["photos"]) == 2  # driver's collection photo + customer's incident photo
    assert len(case["incident_photos"]) == 1
    assert case["reporter_role"] == "customer"

    # Can't close without investigating, or without writing the outcome
    assert client.post(f"/api/admin/incidents/{inc['id']}/status", headers=h,
                       json={"status": "resolved", "resolution": "x" * 10}).status_code == 409
    client.post(f"/api/admin/incidents/{inc['id']}/status", headers=h,
                json={"status": "investigating", "note": "Checking the seal and photos"})
    client.post(f"/api/admin/incidents/{inc['id']}/comments", headers=h,
                json={"note": "Driver has two prior complaints", "internal": True})
    client.post(f"/api/admin/incidents/{inc['id']}/comments", headers=h,
                json={"note": "We've contacted the laundry", "internal": False})
    assert client.post(f"/api/admin/incidents/{inc['id']}/status", headers=h,
                       json={"status": "resolved"}).status_code == 422
    r = client.post(f"/api/admin/incidents/{inc['id']}/status", headers=h,
                    json={"status": "resolved",
                          "resolution": "Shirts found at the laundry and returned."})
    assert r.status_code == 200
    assert r.json()["assigned_admin_name"] == admin.full_name

    # The reporter sees the outcome and public notes, never internal ones (SEC-037)
    mine = client.get(f"/api/incidents/{inc['id']}", headers=auth_header(customer)).json()
    assert mine["status"] == "resolved"
    assert mine["resolution"] == "Shirts found at the laundry and returned."
    notes = [u["note"] for u in mine["updates"]]
    assert "We've contacted the laundry" in notes
    assert "Driver has two prior complaints" not in notes
    assert all(u["author"] in ("LaundryConnect support",) or "customer" in u["author"]
               for u in mine["updates"])

    # Closed: the reporter can't add to it, but an admin can reopen
    assert client.post(f"/api/incidents/{inc['id']}/comments", headers=auth_header(customer),
                       json={"note": "Still missing a sock"}).status_code == 409
    assert client.post(f"/api/admin/incidents/{inc['id']}/status", headers=h,
                       json={"status": "investigating"}).status_code == 200


def test_admin_queue_and_severity(client, customer, admin, accepted_order):
    inc = report(client, customer, order=accepted_order).json()
    h = auth_header(admin)
    queue = client.get("/api/admin/incidents", headers=h).json()
    assert [i["reference"] for i in queue["items"]] == [inc["reference"]]
    r = client.patch(f"/api/admin/incidents/{inc['id']}", headers=h, json={"severity": "critical"})
    assert r.json()["severity"] == "critical"


def test_incident_trail_is_permanent(client, db, customer, accepted_order):
    report(client, customer, order=accepted_order)
    sp = db.begin_nested()
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE incident_updates SET note = 'rewritten'"))
    sp.rollback()


@pytest.mark.parametrize("role", [UserRole.CUSTOMER, UserRole.DRIVER, UserRole.BUSINESS])
def test_only_admins_investigate(client, make_user, role):
    assert client.get("/api/admin/incidents", headers=auth_header(make_user(role))).status_code == 403


def test_admins_use_admin_endpoints_to_report(client, admin):
    assert report(client, admin, "fraud", description="Testing a fraud report").status_code == 403


# ======================= Suspension (SEC-044) =======================

def test_suspending_driver_blocks_them_and_frees_their_jobs(client, db, customer, driver, admin,
                                                            accepted_order):
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    inc = report(client, customer, "conduct", order=accepted_order,
                 description="Driver was abusive on the phone.").json()

    r = client.post(f"/api/admin/users/{driver.id}/suspend", headers=auth_header(admin),
                    json={"reason": "Abuse complaint under investigation",
                          "incident_id": inc["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["jobs_released"] == 1

    assert client.get("/api/driver/jobs", headers=auth_header(driver)).status_code == 403
    db.refresh(job)
    assert job.status == JobStatus.OPEN and job.driver_id is None
    assert driver.driver_profile.is_available is False
    case = client.get(f"/api/admin/incidents/{inc['id']}", headers=auth_header(admin)).json()
    assert any(u["internal"] and "Suspended" in u["note"] for u in case["updates"])

    assert client.post(f"/api/admin/users/{driver.id}/suspend", headers=auth_header(admin),
                       json={"reason": "Again"}).status_code == 409
    r = client.post(f"/api/admin/users/{driver.id}/reinstate", headers=auth_header(admin),
                    json={"reason": "Complaint not upheld"})
    assert r.json()["status"] == "active"
    assert driver.status == AccountStatus.ACTIVE


def test_cannot_suspend_admins(client, make_user, admin):
    other_admin = make_user(UserRole.ADMIN)
    r = client.post(f"/api/admin/users/{other_admin.id}/suspend", headers=auth_header(admin),
                    json={"reason": "Testing suspension"})
    assert r.status_code == 403
