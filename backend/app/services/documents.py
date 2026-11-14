"""Verification documents: what's allowed, what's required, upload checks,
and tamper detection (SEC-001, SEC-002, SEC-043)."""

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath

from fastapi import HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DriverProfile, User, VerificationDocument
from app.models.enums import DocumentType as D
from app.models.enums import UserRole, VehicleType
from app.models.enums import VerificationStatus as V
from app.schemas.documents import DocumentOut, DocumentsOverview
from app.services import audit, files, storage

# ---------- Rules ----------

ALLOWED_TYPES: dict[UserRole, frozenset[D]] = {
    UserRole.DRIVER: frozenset({
        D.NATIONAL_ID, D.PASSPORT, D.DRIVERS_LICENCE, D.SELFIE,
        D.PROFILE_PHOTO, D.VEHICLE_REGISTRATION, D.OTHER,
    }),
    UserRole.BUSINESS: frozenset({
        D.BUSINESS_REGISTRATION, D.PROOF_OF_ADDRESS, D.TAX_CLEARANCE, D.OTHER,
    }),
}

# A selfie or profile photo must be a photo, not a PDF
IMAGE_ONLY = frozenset({D.SELFIE, D.PROFILE_PHOTO})


@dataclass(frozen=True)
class Requirement:
    name: str
    accepted: frozenset[D]


def driver_requirements(profile: DriverProfile) -> list[Requirement]:
    reqs = [
        Requirement("Identity document (SA ID or passport)", frozenset({D.NATIONAL_ID, D.PASSPORT})),
        Requirement("Selfie", frozenset({D.SELFIE})),
        Requirement("Profile photo", frozenset({D.PROFILE_PHOTO})),
    ]
    # Cyclists don't need a licence; everyone with a motor vehicle does
    if profile.vehicle_type != VehicleType.BICYCLE:
        reqs.append(Requirement("Driver's licence", frozenset({D.DRIVERS_LICENCE})))
    return reqs


BUSINESS_REQUIREMENTS = [
    Requirement("Business registration (CIPC)", frozenset({D.BUSINESS_REGISTRATION})),
    Requirement("Proof of business address", frozenset({D.PROOF_OF_ADDRESS})),
]


def documents_for(db: Session, user_id: uuid.UUID) -> list[VerificationDocument]:
    return list(db.scalars(
        select(VerificationDocument)
        .where(VerificationDocument.user_id == user_id)
        .order_by(VerificationDocument.uploaded_at.desc())
    ))


def requirement_status(docs: list[VerificationDocument], reqs: list[Requirement]) -> list[dict]:
    """For each requirement: approved if any matching doc is approved, otherwise
    the state of the most recent upload, or missing."""
    out = []
    for req in reqs:
        matching = [d for d in docs if d.document_type in req.accepted]  # newest first
        approved = next((d for d in matching if d.status == V.APPROVED), None)
        current = approved or (matching[0] if matching else None)
        out.append({
            "name": req.name,
            "accepted_types": sorted(t.value for t in req.accepted),
            "status": current.status.value if current else "missing",
            "document_id": current.id if current else None,
            "notes": current.review_notes if current else None,
        })
    return out


def unmet(statuses: list[dict]) -> list[str]:
    return [s["name"] for s in statuses if s["status"] != V.APPROVED.value]


def requirements_for(user: User) -> list[Requirement]:
    if user.role == UserRole.DRIVER and user.driver_profile is not None:
        return driver_requirements(user.driver_profile)
    if user.role == UserRole.BUSINESS:
        return BUSINESS_REQUIREMENTS
    return []


def overview(db: Session, user: User) -> DocumentsOverview:
    """A user's documents plus the checklist of what's required (newest first).
    For a business, pass the owner's account."""
    docs = documents_for(db, user.id)
    statuses = requirement_status(docs, requirements_for(user))
    return DocumentsOverview(
        documents=[DocumentOut.model_validate(d) for d in docs],
        requirements=statuses,
        ready_for_review=all(s["status"] in ("pending", "approved") for s in statuses),
        all_approved=not unmet(statuses),
    )


def ensure_requirements_met(db: Session, user: User) -> None:
    """Blocks approving a driver/business until its required documents are approved."""
    missing = unmet(requirement_status(documents_for(db, user.id), requirements_for(user)))
    if missing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot approve yet. These documents still need to be approved: "
            + ", ".join(missing),
        )


# ---------- Upload ----------

_read_limited = files.read_limited
_detect = files.detect


def _clean_filename(name: str | None) -> str:
    # Kept for display only; strip any path and control characters
    base = PurePath(name or "upload").name
    return re.sub(r"[\x00-\x1f\x7f]", "", base)[:255] or "upload"


def upload(
    db: Session, owner: User, doc_type: D, file: UploadFile, request: Request
) -> VerificationDocument:
    if doc_type not in ALLOWED_TYPES.get(owner.role, frozenset()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"{doc_type.value} is not a document type for your account")

    data = _read_limited(file)
    detected = _detect(data)
    if detected is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            "Only JPEG, PNG or PDF files are accepted")
    mime, ext = detected
    if doc_type in IMAGE_ONLY and mime == "application/pdf":
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            "A selfie or profile photo must be a JPEG or PNG image")

    doc_id = uuid.uuid4()
    path = storage.save(str(owner.id), f"{doc_id}.{ext}", data)

    try:
        # An older upload of the same type still awaiting review is replaced,
        # so admins only review the latest one.
        for old in db.scalars(select(VerificationDocument).where(
            VerificationDocument.user_id == owner.id,
            VerificationDocument.document_type == doc_type,
            VerificationDocument.status == V.PENDING,
        )):
            old.status = V.REJECTED
            old.review_notes = "Replaced by a newer upload"

        doc = VerificationDocument(
            id=doc_id,
            user_id=owner.id,
            document_type=doc_type,
            file_path=path,
            original_filename=_clean_filename(file.filename),
            content_type=mime,
            file_size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
        db.add(doc)
        audit.record(db, "document.uploaded", actor_id=owner.id, entity_type="verification_document",
                     entity_id=doc_id, details={"type": doc_type.value, "size": len(data)},
                     request=request)
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(path)  # don't leave orphan files behind
        raise
    return doc


# ---------- Admin review ----------

def review(
    db: Session,
    doc: VerificationDocument,
    admin: User,
    *,
    approve: bool,
    notes: str | None,
    request: Request,
) -> None:
    new_status = V.APPROVED if approve else V.REJECTED
    if doc.status == new_status:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Document is already {new_status.value}")
    previous = doc.status
    doc.status = new_status
    doc.reviewed_by_id = admin.id
    doc.reviewed_at = datetime.now(UTC)
    doc.review_notes = notes
    audit.record(db, f"document.{new_status.value}", actor_id=admin.id,
                 entity_type="verification_document", entity_id=doc.id,
                 details={"type": doc.document_type.value, "previous_status": previous.value,
                          "notes": notes},
                 request=request)
    db.commit()


# ---------- Download ----------

def file_response(
    db: Session, doc: VerificationDocument, viewer: User, request: Request
) -> Response:
    """Returns the file after confirming it is byte-for-byte what was uploaded."""
    ext = doc.file_path.rsplit(".", 1)[-1]
    return files.serve(
        db, path=doc.file_path, expected_sha256=doc.sha256, content_type=doc.content_type,
        # Our own safe filename, never the user's, in the header
        download_name=f"{doc.document_type.value}.{ext}",
        viewer=viewer, owner_id=doc.user_id, action_prefix="document",
        entity_type="verification_document", entity_id=doc.id, request=request,
    )
