"""Verification document upload, review and tamper detection (SEC-001, SEC-002, SEC-043)."""

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import AuditLog, VerificationDocument
from app.models.enums import BusinessStaffRole, UserRole, VehicleType
from app.models.enums import VerificationStatus as V
from tests.conftest import auth_header

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
PDF = b"%PDF-1.7\n" + b"0" * 200
EXE = b"MZ\x90\x00" + b"\x00" * 200  # Windows program


def upload(client, user, doc_type, content=PNG, filename="file.png", mime="image/png"):
    return client.post(
        "/api/documents",
        headers=auth_header(user),
        data={"document_type": doc_type},
        files={"file": (filename, content, mime)},
    )


def checklist(client, user):
    r = client.get("/api/documents", headers=auth_header(user))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def admin(make_user):
    return make_user(UserRole.ADMIN)


# ---------- Uploading ----------

def test_driver_uploads_id_document(client, make_driver, db, isolated_uploads):
    driver = make_driver()
    r = upload(client, driver, "national_id", PDF, "my id.pdf", "application/pdf")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["content_type"] == "application/pdf"
    assert body["original_filename"] == "my id.pdf"

    doc = db.get(VerificationDocument, body["id"])
    assert doc.sha256 == hashlib.sha256(PDF).hexdigest()
    stored = isolated_uploads / doc.file_path
    assert stored.read_bytes() == PDF
    # Stored under a random name, never the user's filename
    assert stored.name == f"{doc.id}.pdf"


def test_checklist_tracks_required_documents(client, make_driver):
    driver = make_driver()
    first = checklist(client, driver)
    assert {r["status"] for r in first["requirements"]} == {"missing"}
    assert len(first["requirements"]) == 4  # ID, selfie, profile photo, licence
    assert first["ready_for_review"] is False

    upload(client, driver, "passport", PDF, mime="application/pdf")  # passport also satisfies ID
    upload(client, driver, "selfie", JPEG, "me.jpg", "image/jpeg")
    upload(client, driver, "profile_photo")
    upload(client, driver, "drivers_licence")

    after = checklist(client, driver)
    assert {r["status"] for r in after["requirements"]} == {"pending"}
    assert after["ready_for_review"] is True
    assert after["all_approved"] is False
    assert len(after["documents"]) == 4


def test_cyclists_do_not_need_a_licence(client, make_driver, db):
    driver = make_driver()
    driver.driver_profile.vehicle_type = VehicleType.BICYCLE
    db.flush()
    names = [r["name"] for r in checklist(client, driver)["requirements"]]
    assert "Driver's licence" not in names
    assert len(names) == 3


def test_disguised_file_is_rejected(client, make_driver):
    # A program renamed to .jpg with an image content type
    r = upload(client, make_driver(), "national_id", EXE, "id.jpg", "image/jpeg")
    assert r.status_code == 415


def test_selfie_must_be_an_image(client, make_driver):
    r = upload(client, make_driver(), "selfie", PDF, "selfie.pdf", "application/pdf")
    assert r.status_code == 415


def test_file_size_limit(client, make_driver, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    too_big = PNG + b"\x00" * (1024 * 1024)
    assert upload(client, make_driver(), "national_id", too_big).status_code == 413


def test_empty_file_rejected(client, make_driver):
    assert upload(client, make_driver(), "national_id", b"").status_code == 422


def test_driver_cannot_upload_business_documents(client, make_driver):
    assert upload(client, make_driver(), "business_registration", PDF).status_code == 422


def test_path_in_filename_is_stripped(client, make_driver):
    r = upload(client, make_driver(), "national_id", PNG, "../../etc/evil.png")
    assert r.status_code == 201
    assert r.json()["original_filename"] == "evil.png"


@pytest.mark.parametrize("role", [UserRole.CUSTOMER, UserRole.ADMIN])
def test_roles_without_documents_cannot_upload(client, make_user, role):
    assert upload(client, make_user(role), "national_id").status_code == 403


def test_only_business_owner_uploads_business_documents(client, make_business, add_staff):
    biz = make_business(V.PENDING)
    manager = add_staff(biz, BusinessStaffRole.MANAGER)
    assert upload(client, manager, "business_registration", PDF).status_code == 403
    assert upload(client, biz.owner, "business_registration", PDF).status_code == 201


def test_reupload_replaces_pending_document(client, make_driver, db):
    driver = make_driver()
    old_id = upload(client, driver, "selfie").json()["id"]
    new_id = upload(client, driver, "selfie", JPEG, "better.jpg", "image/jpeg").json()["id"]

    old = db.get(VerificationDocument, old_id)
    assert old.status == V.REJECTED
    assert old.review_notes == "Replaced by a newer upload"
    selfie = next(r for r in checklist(client, driver)["requirements"] if r["name"] == "Selfie")
    assert selfie["document_id"] == new_id
    assert selfie["status"] == "pending"


def test_uploads_are_audited(client, make_driver, db):
    driver = make_driver()
    upload(client, driver, "selfie")
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "document.uploaded"))
    assert entry.actor_user_id == driver.id
    assert entry.details["type"] == "selfie"


# ---------- Downloading ----------

def test_owner_can_view_own_file_with_safe_headers(client, make_driver, db):
    driver = make_driver()
    doc_id = upload(client, driver, "national_id", PDF, mime="application/pdf").json()["id"]
    r = client.get(f"/api/documents/{doc_id}/file", headers=auth_header(driver))
    assert r.status_code == 200
    assert r.content == PDF
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "no-store" in r.headers["cache-control"]
    # Viewing your own document isn't logged as an access to someone's data
    assert db.scalar(select(AuditLog).where(AuditLog.action == "document.viewed")) is None


def test_other_users_cannot_see_my_documents(client, make_driver):
    me, other = make_driver(), make_driver()
    doc_id = upload(client, me, "national_id").json()["id"]
    assert client.get(f"/api/documents/{doc_id}/file", headers=auth_header(other)).status_code == 404
    assert checklist(client, other)["documents"] == []


def test_tampered_file_is_detected(client, make_driver, admin, db, isolated_uploads):
    driver = make_driver()
    doc_id = upload(client, driver, "national_id").json()["id"]
    doc = db.get(VerificationDocument, doc_id)
    Path(isolated_uploads / doc.file_path).write_bytes(PNG + b"edited")

    r = client.get(f"/api/admin/documents/{doc_id}/file", headers=auth_header(admin))
    assert r.status_code == 409
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "document.integrity_failed"))
    assert entry.actor_user_id == admin.id


# ---------- Admin review ----------

def test_non_admins_cannot_review_documents(client, make_driver):
    driver = make_driver()
    doc_id = upload(client, driver, "selfie").json()["id"]
    h = auth_header(driver)
    assert client.get("/api/admin/documents", headers=h).status_code == 403
    assert client.post(f"/api/admin/documents/{doc_id}/approve", headers=h).status_code == 403
    assert client.get(f"/api/admin/documents/{doc_id}/file", headers=h).status_code == 403


def test_admin_review_queue_and_viewing_is_audited(client, make_driver, admin, db):
    driver = make_driver()
    doc_id = upload(client, driver, "selfie").json()["id"]

    queue = client.get("/api/admin/documents", headers=auth_header(admin)).json()
    assert queue["total"] == 1
    assert queue["items"][0]["id"] == doc_id
    assert queue["items"][0]["owner_role"] == "driver"

    r = client.get(f"/api/admin/documents/{doc_id}/file", headers=auth_header(admin))
    assert r.status_code == 200 and r.content == PNG
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "document.viewed"))
    assert entry.actor_user_id == admin.id
    assert entry.entity_id == doc_id


def test_rejected_document_reason_shown_to_driver(client, make_driver, admin):
    driver = make_driver()
    doc_id = upload(client, driver, "selfie").json()["id"]
    h = auth_header(admin)
    assert client.post(f"/api/admin/documents/{doc_id}/reject", headers=h).status_code == 422
    r = client.post(f"/api/admin/documents/{doc_id}/reject", headers=h,
                    json={"reason": "Face not clearly visible"})
    assert r.status_code == 200
    selfie = next(r for r in checklist(client, driver)["requirements"] if r["name"] == "Selfie")
    assert selfie["status"] == "rejected"
    assert selfie["notes"] == "Face not clearly visible"


def test_document_cannot_be_approved_twice(client, make_driver, admin):
    doc_id = upload(client, make_driver(), "selfie").json()["id"]
    h = auth_header(admin)
    assert client.post(f"/api/admin/documents/{doc_id}/approve", headers=h).status_code == 200
    assert client.post(f"/api/admin/documents/{doc_id}/approve", headers=h).status_code == 409


# ---------- Approval gating (end to end) ----------

def test_driver_cannot_be_approved_until_documents_are(client, make_driver, admin):
    driver = make_driver()
    h = auth_header(admin)

    r = client.post(f"/api/admin/drivers/{driver.id}/approve", headers=h)
    assert r.status_code == 409
    assert "Selfie" in r.json()["detail"]

    ids = [
        upload(client, driver, "national_id", PDF, mime="application/pdf").json()["id"],
        upload(client, driver, "selfie").json()["id"],
        upload(client, driver, "profile_photo").json()["id"],
        upload(client, driver, "drivers_licence").json()["id"],
    ]
    for doc_id in ids[:-1]:
        client.post(f"/api/admin/documents/{doc_id}/approve", headers=h)

    r = client.post(f"/api/admin/drivers/{driver.id}/approve", headers=h)
    assert r.status_code == 409
    assert r.json()["detail"].endswith("Driver's licence")

    client.post(f"/api/admin/documents/{ids[-1]}/approve", headers=h)
    overview = client.get(f"/api/admin/drivers/{driver.id}/documents", headers=h).json()
    assert overview["all_approved"] is True

    r = client.post(f"/api/admin/drivers/{driver.id}/approve", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["verification_status"] == "approved"


def test_business_cannot_be_approved_until_documents_are(client, make_business, admin):
    biz = make_business(V.PENDING)
    h = auth_header(admin)
    assert client.post(f"/api/admin/businesses/{biz.id}/approve", headers=h).status_code == 409

    for doc_type in ("business_registration", "proof_of_address"):
        doc_id = upload(client, biz.owner, doc_type, PDF, mime="application/pdf").json()["id"]
        client.post(f"/api/admin/documents/{doc_id}/approve", headers=h)

    overview = client.get(f"/api/admin/businesses/{biz.id}/documents", headers=h).json()
    assert overview["all_approved"] is True
    assert client.post(f"/api/admin/businesses/{biz.id}/approve", headers=h).status_code == 200
