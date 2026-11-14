"""Administrator review of driver and business registrations (UR-004, UAT-005).

Every route here requires an admin (SEC-020).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession, require_admin
from app.models import BusinessProfile, DriverProfile, VerificationDocument
from app.models.enums import VerificationStatus
from app.schemas.admin import BusinessReviewOut, DriverReviewOut, Page, RejectIn
from app.schemas.documents import AdminDocumentOut, ApproveDocumentIn, DocumentsOverview
from app.services import documents, verification

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


# ---------- Drivers ----------

def _driver_out(p: DriverProfile) -> DriverReviewOut:
    return DriverReviewOut(
        user_id=p.user_id,
        full_name=p.user.full_name,
        email=p.user.email,
        phone=p.user.phone,
        id_number=p.id_number,
        vehicle_type=p.vehicle_type,
        vehicle_registration=p.vehicle_registration,
        verification_status=p.verification_status,
        verified_at=p.verified_at,
        verified_by_id=p.verified_by_id,
        rejection_reason=p.rejection_reason,
        registered_at=p.created_at,
    )


def _lock_driver(db: DbSession, user_id: uuid.UUID) -> DriverProfile:
    # FOR UPDATE: if two admins act on the same driver at once, the second
    # waits and then sees the first decision instead of overwriting it.
    profile = db.get(DriverProfile, user_id, with_for_update=True)
    if profile is None:
        raise _not_found("Driver")
    return profile


@router.get("/drivers", response_model=Page[DriverReviewOut])
def list_drivers(
    db: DbSession,
    status_: Annotated[VerificationStatus, Query(alias="status")] = VerificationStatus.PENDING,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[DriverReviewOut]:
    """Drivers in a given review state, oldest first (first come, first reviewed)."""
    where = DriverProfile.verification_status == status_
    total = db.scalar(select(func.count()).select_from(DriverProfile).where(where))
    rows = db.scalars(
        select(DriverProfile).join(DriverProfile.user).where(where)
        .order_by(DriverProfile.created_at, DriverProfile.user_id).limit(limit).offset(offset)
    ).all()
    return Page(items=[_driver_out(p) for p in rows], total=total, limit=limit, offset=offset)


@router.get("/drivers/{user_id}", response_model=DriverReviewOut)
def get_driver(user_id: uuid.UUID, db: DbSession) -> DriverReviewOut:
    profile = db.get(DriverProfile, user_id)
    if profile is None:
        raise _not_found("Driver")
    return _driver_out(profile)


@router.post("/drivers/{user_id}/approve", response_model=DriverReviewOut)
def approve_driver(
    user_id: uuid.UUID, db: DbSession, admin: AdminUser, request: Request
) -> DriverReviewOut:
    profile = _lock_driver(db, user_id)
    documents.ensure_requirements_met(db, profile.user)  # SEC-001, SEC-002
    verification.approve(db, profile, admin, request)
    return _driver_out(profile)


@router.post("/drivers/{user_id}/reject", response_model=DriverReviewOut)
def reject_driver(
    user_id: uuid.UUID, body: RejectIn, db: DbSession, admin: AdminUser, request: Request
) -> DriverReviewOut:
    profile = _lock_driver(db, user_id)
    verification.reject(db, profile, admin, body.reason, request)
    return _driver_out(profile)


# ---------- Businesses ----------

def _business_out(b: BusinessProfile) -> BusinessReviewOut:
    return BusinessReviewOut(
        id=b.id,
        business_name=b.business_name,
        registration_number=b.registration_number,
        description=b.description,
        contact_phone=b.contact_phone,
        contact_email=b.contact_email,
        address_line=b.address_line,
        suburb=b.suburb,
        city=b.city,
        province=b.province,
        postal_code=b.postal_code,
        owner_user_id=b.owner_user_id,
        owner_name=b.owner.full_name,
        owner_email=b.owner.email,
        verification_status=b.verification_status,
        verified_at=b.verified_at,
        verified_by_id=b.verified_by_id,
        rejection_reason=b.rejection_reason,
        registered_at=b.created_at,
    )


def _lock_business(db: DbSession, business_id: uuid.UUID) -> BusinessProfile:
    business = db.get(BusinessProfile, business_id, with_for_update=True)
    if business is None:
        raise _not_found("Business")
    return business


@router.get("/businesses", response_model=Page[BusinessReviewOut])
def list_businesses(
    db: DbSession,
    status_: Annotated[VerificationStatus, Query(alias="status")] = VerificationStatus.PENDING,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[BusinessReviewOut]:
    where = BusinessProfile.verification_status == status_
    total = db.scalar(select(func.count()).select_from(BusinessProfile).where(where))
    rows = db.scalars(
        select(BusinessProfile).join(BusinessProfile.owner).where(where)
        .order_by(BusinessProfile.created_at, BusinessProfile.id).limit(limit).offset(offset)
    ).all()
    return Page(items=[_business_out(b) for b in rows], total=total, limit=limit, offset=offset)


@router.get("/businesses/{business_id}", response_model=BusinessReviewOut)
def get_business(business_id: uuid.UUID, db: DbSession) -> BusinessReviewOut:
    business = db.get(BusinessProfile, business_id)
    if business is None:
        raise _not_found("Business")
    return _business_out(business)


@router.post("/businesses/{business_id}/approve", response_model=BusinessReviewOut)
def approve_business(
    business_id: uuid.UUID, db: DbSession, admin: AdminUser, request: Request
) -> BusinessReviewOut:
    business = _lock_business(db, business_id)
    documents.ensure_requirements_met(db, business.owner)  # SEC-043
    verification.approve(db, business, admin, request)
    return _business_out(business)


@router.post("/businesses/{business_id}/reject", response_model=BusinessReviewOut)
def reject_business(
    business_id: uuid.UUID, body: RejectIn, db: DbSession, admin: AdminUser, request: Request
) -> BusinessReviewOut:
    business = _lock_business(db, business_id)
    verification.reject(db, business, admin, body.reason, request)
    return _business_out(business)


# ---------- Verification documents ----------

@router.get("/drivers/{user_id}/documents", response_model=DocumentsOverview)
def driver_documents(user_id: uuid.UUID, db: DbSession) -> DocumentsOverview:
    profile = db.get(DriverProfile, user_id)
    if profile is None:
        raise _not_found("Driver")
    return documents.overview(db, profile.user)


@router.get("/businesses/{business_id}/documents", response_model=DocumentsOverview)
def business_documents(business_id: uuid.UUID, db: DbSession) -> DocumentsOverview:
    business = db.get(BusinessProfile, business_id)
    if business is None:
        raise _not_found("Business")
    return documents.overview(db, business.owner)


def _admin_doc_out(d: VerificationDocument) -> AdminDocumentOut:
    return AdminDocumentOut(
        id=d.id, document_type=d.document_type, original_filename=d.original_filename,
        content_type=d.content_type, file_size=d.file_size, status=d.status,
        review_notes=d.review_notes, uploaded_at=d.uploaded_at, reviewed_at=d.reviewed_at,
        user_id=d.user_id, owner_name=d.user.full_name, owner_role=d.user.role.value,
    )


@router.get("/documents", response_model=Page[AdminDocumentOut])
def list_documents(
    db: DbSession,
    status_: Annotated[VerificationStatus, Query(alias="status")] = VerificationStatus.PENDING,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Page[AdminDocumentOut]:
    """The document review queue, oldest first."""
    where = VerificationDocument.status == status_
    total = db.scalar(select(func.count()).select_from(VerificationDocument).where(where))
    rows = db.scalars(
        select(VerificationDocument).where(where)
        .order_by(VerificationDocument.uploaded_at, VerificationDocument.id)
        .limit(limit).offset(offset)
    ).all()
    return Page(items=[_admin_doc_out(d) for d in rows], total=total, limit=limit, offset=offset)


def _get_doc(db: DbSession, document_id: uuid.UUID, lock: bool = False) -> VerificationDocument:
    doc = db.get(VerificationDocument, document_id, with_for_update=lock)
    if doc is None:
        raise _not_found("Document")
    return doc


@router.get("/documents/{document_id}/file")
def document_file(
    document_id: uuid.UUID, db: DbSession, admin: AdminUser, request: Request
) -> Response:
    """View the uploaded file. Each view is recorded in the audit log."""
    return documents.file_response(db, _get_doc(db, document_id), admin, request)


@router.post("/documents/{document_id}/approve", response_model=AdminDocumentOut)
def approve_document(
    document_id: uuid.UUID,
    db: DbSession,
    admin: AdminUser,
    request: Request,
    body: ApproveDocumentIn | None = None,
) -> AdminDocumentOut:
    doc = _get_doc(db, document_id, lock=True)
    documents.review(db, doc, admin, approve=True, notes=body.notes if body else None,
                     request=request)
    return _admin_doc_out(doc)


@router.post("/documents/{document_id}/reject", response_model=AdminDocumentOut)
def reject_document(
    document_id: uuid.UUID, body: RejectIn, db: DbSession, admin: AdminUser, request: Request
) -> AdminDocumentOut:
    doc = _get_doc(db, document_id, lock=True)
    documents.review(db, doc, admin, approve=False, notes=body.reason, request=request)
    return _admin_doc_out(doc)
