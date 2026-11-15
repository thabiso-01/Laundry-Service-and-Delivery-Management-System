"""POPIA data-subject rights.

* Access (s23): `export()` gathers everything we hold about the user.
* Deletion (s24): `delete_account()` wipes personal details. Some records must
  be kept (s14: financial records for SARS, 5 years; evidence for disputes and
  investigations), so those are kept but stripped of identifying details where
  possible and linked only to an anonymous, deactivated account.

Retention summary is returned to the user so they can see exactly what happened.
"""

import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import mfa
from app.core.security import hash_password, verify_password
from app.models import (
    AuditLog,
    DeliveryJob,
    DriverLocation,
    Incident,
    Notification,
    Order,
    Payment,
    Review,
    User,
    VerificationDocument,
)
from app.models.enums import (
    AccountStatus,
    BusinessStaffRole,
    IncidentStatus,
    OrderStatus,
    UserRole,
)
from app.services import audit, jobs, storage

FINISHED_ORDERS = {OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.DECLINED}
OPEN_INCIDENTS = {IncidentStatus.OPEN, IncidentStatus.INVESTIGATING}
REMOVED = "(removed at the customer's request)"

RETAINED = [
    "Orders and payments – amounts, dates and suburb only (tax records, kept 5 years)",
    "Handover, seal and photo records (evidence if a dispute or claim arises)",
    "Reports you made and their investigation notes",
    "Security log entries (sign-ins and actions), linked only to an anonymous account ID",
]


# ---------- Access: export ----------

def _rows(items, fields: list[str]) -> list[dict[str, Any]]:
    return [{f: getattr(i, f) for f in fields} for i in items]


def export(db: Session, user: User, request: Request) -> dict[str, Any]:
    data: dict[str, Any] = {
        "generated_at": datetime.now(UTC),
        "about": "All personal information LaundryConnect holds about you (POPIA section 23).",
        "account": {
            "id": user.id, "email": user.email, "full_name": user.full_name, "phone": user.phone,
            "role": user.role, "status": user.status, "created_at": user.created_at,
            "last_login_at": user.last_login_at, "privacy_consent_at": user.privacy_consent_at,
            "two_step_login_enabled": user.mfa_enabled_at is not None,
        },
    }
    if user.customer_profile:
        data["home_address"] = _rows([user.customer_profile], [
            "address_line", "suburb", "city", "province", "postal_code", "latitude", "longitude"])[0]
    if user.driver_profile:
        data["driver_profile"] = _rows([user.driver_profile], [
            "id_number", "vehicle_type", "vehicle_registration", "verification_status",
            "verified_at", "rejection_reason", "is_available"])[0]
        driver_jobs = db.scalars(select(DeliveryJob).where(DeliveryJob.driver_id == user.id))
        data["driver_jobs"] = [{"order_number": j.order.order_number, "kind": j.kind,
                                "status": j.status, "fee_cents": j.driver_fee_cents,
                                "assigned_at": j.assigned_at, "completed_at": j.completed_at}
                               for j in driver_jobs]
        data["location_history"] = _rows(
            db.scalars(select(DriverLocation).where(DriverLocation.driver_id == user.id)
                       .order_by(DriverLocation.recorded_at)),
            ["latitude", "longitude", "recorded_at", "off_route"])
        data["ratings_received"] = _rows(
            db.scalars(select(Review).where(Review.driver_id == user.id)),
            ["rating", "comment", "created_at"])  # reviewers are other people: not included
    if user.staff_membership:
        m = user.staff_membership
        data["laundry_business"] = {"business_name": m.business.business_name,
                                    "staff_role": m.staff_role, "is_active": m.is_active,
                                    "since": m.created_at}

    orders = db.scalars(select(Order).where(Order.customer_id == user.id)
                        .order_by(Order.created_at)).all()
    data["orders"] = [{
        "order_number": o.order_number, "status": o.status, "laundry": o.business.business_name,
        "placed_at": o.created_at,
        "items": _rows(o.items, ["service_name", "quantity", "unit_price_cents", "line_total_cents"]),
        "total_cents": o.final_total_cents, "paid_cents": o.paid_cents,
        "collection_address": {k: getattr(o, f"collection_{k}") for k in (
            "address_line", "suburb", "city", "postal_code", "latitude", "longitude")},
        "delivery_address": {k: getattr(o, f"delivery_{k}") for k in (
            "address_line", "suburb", "city", "postal_code", "latitude", "longitude")},
        "notes": o.customer_notes,
        "history": _rows(o.events, ["to_status", "created_at", "note"]),
        "payments": _rows(db.scalars(select(Payment).where(Payment.order_id == o.id)),
                          ["reference", "status", "amount_cents", "paid_at"]),
    } for o in orders]

    data["documents"] = _rows(
        db.scalars(select(VerificationDocument).where(VerificationDocument.user_id == user.id)),
        ["document_type", "original_filename", "status", "uploaded_at", "review_notes"])
    data["reviews_written"] = _rows(
        db.scalars(select(Review).where(Review.customer_id == user.id)),
        ["target", "rating", "comment", "created_at"])
    data["reports_made"] = _rows(
        db.scalars(select(Incident).where(Incident.reported_by_id == user.id)),
        ["reference", "category", "description", "status", "created_at", "resolution"])
    data["notifications"] = _rows(
        db.scalars(select(Notification).where(Notification.user_id == user.id)
                   .order_by(Notification.created_at)),
        ["title", "body", "created_at", "read_at"])
    data["security_log"] = _rows(
        db.scalars(select(AuditLog).where(AuditLog.actor_user_id == user.id)
                   .order_by(AuditLog.created_at.desc()).limit(500)),
        ["action", "created_at", "ip_address", "user_agent"])

    audit.record(db, "privacy.data_exported", actor_id=user.id, entity_type="user",
                 entity_id=user.id, request=request)
    db.commit()
    return jsonable_encoder(data)


# ---------- Deletion ----------

def _blockers(db: Session, user: User) -> list[str]:
    reasons = []
    if user.role == UserRole.ADMIN:
        reasons.append("Administrator accounts are removed by another administrator")
    active_orders = db.scalar(select(Order.order_number).where(
        Order.customer_id == user.id, Order.status.not_in(FINISHED_ORDERS)).limit(1))
    if active_orders:
        reasons.append(f"Order {active_orders} isn't finished yet. Wait for delivery or cancel it")
    if db.scalar(select(DeliveryJob.id).where(
            DeliveryJob.driver_id == user.id, DeliveryJob.status.in_(jobs.ACTIVE_JOB)).limit(1)):
        reasons.append("You have an active delivery job. Complete it or give it back first")
    m = user.staff_membership
    if m and m.staff_role == BusinessStaffRole.OWNER:
        reasons.append("You own a laundry business. Contact support to close it or hand it "
                       "over before deleting your account")
    return reasons


def delete_account(db: Session, user: User, password: str, code: str | None,
                   request: Request) -> dict[str, Any]:
    valid, _ = verify_password(password, user.password_hash)
    if not valid:
        audit.record(db, "privacy.delete_failed", actor_id=user.id,
                     details={"reason": "wrong_password"}, request=request)
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password is incorrect")
    if user.mfa_enabled_at:
        secret = mfa.decrypt(user.mfa_secret_encrypted or "")
        if not code or not secret or mfa.verify(secret, code, user.mfa_last_step) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Enter the current code from your authenticator app")
    blockers = _blockers(db, user)
    if blockers:
        raise HTTPException(status.HTTP_409_CONFLICT, "; ".join(blockers))

    now = datetime.now(UTC)
    removed: dict[str, int] = {}

    # Identity and login
    user.full_name = "Deleted user"
    user.email = f"deleted-{user.id.hex}@deleted.invalid"
    user.phone = None
    user.password_hash = hash_password(secrets.token_urlsafe(32))  # nobody can log in
    user.password_changed_at = now  # ends every session
    user.mfa_secret_encrypted = None
    user.mfa_enabled_at = None
    user.mfa_recovery_hashes = None
    user.status = AccountStatus.DEACTIVATED
    user.privacy_consent_at = None
    user.deleted_at = now

    if user.customer_profile:
        p = user.customer_profile
        p.address_line = p.suburb = p.city = p.province = p.postal_code = None
        p.latitude = p.longitude = None
    if user.driver_profile:
        d = user.driver_profile
        d.id_number = f"DELETED-{user.id.hex[:12]}"
        d.vehicle_registration = None
        d.is_available = False
    if user.staff_membership:
        user.staff_membership.is_active = False

    # ID documents: files and records
    docs = db.scalars(select(VerificationDocument).where(VerificationDocument.user_id == user.id)).all()
    for doc in docs:
        storage.delete(doc.file_path)
        db.delete(doc)
    removed["identity_documents"] = len(docs)

    # Orders are financial records: keep amounts and suburb, drop street, notes, exact spot
    orders = db.scalars(select(Order).where(Order.customer_id == user.id)).all()
    for o in orders:
        for prefix in ("collection", "delivery"):
            setattr(o, f"{prefix}_address_line", REMOVED)
            setattr(o, f"{prefix}_postal_code", None)
            for axis in ("latitude", "longitude"):  # ~1 km precision
                setattr(o, f"{prefix}_{axis}", round(getattr(o, f"{prefix}_{axis}"), 2))
        o.customer_notes = None
    removed["orders_anonymised"] = len(orders)

    removed["notifications"] = db.execute(
        delete(Notification).where(Notification.user_id == user.id)).rowcount
    reviews = db.scalars(select(Review).where(Review.customer_id == user.id)).all()
    for r in reviews:
        r.comment = None  # the star rating stays, so laundries' averages don't jump
    removed["review_comments"] = len(reviews)

    # Location history, except trips still under investigation
    investigated = select(Incident.order_id).where(Incident.status.in_(OPEN_INCIDENTS),
                                                   Incident.order_id.is_not(None))
    keep_jobs = select(DeliveryJob.id).where(DeliveryJob.order_id.in_(investigated))
    removed["location_points"] = db.execute(delete(DriverLocation).where(
        DriverLocation.driver_id == user.id, DriverLocation.job_id.not_in(keep_jobs))).rowcount

    audit.record(db, "privacy.account_deleted", actor_id=user.id, entity_type="user",
                 entity_id=user.id, details=removed, request=request)
    db.commit()
    return {"deleted": True, "removed": removed, "kept": RETAINED}
