"""Drivers and business owners upload and view their own verification documents."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response

from app.api.deps import CurrentUser, DbSession
from app.models import User, VerificationDocument
from app.models.enums import BusinessStaffRole, DocumentType, UserRole
from app.schemas.documents import DocumentOut, DocumentsOverview  # noqa: F401 (response models)
from app.services import documents

router = APIRouter(prefix="/api/documents", tags=["documents"])


def require_document_owner(user: CurrentUser) -> User:
    """Drivers, and business *owners* (they are accountable for the business's
    paperwork). Customers and admins have no verification documents."""
    if user.role == UserRole.DRIVER and user.driver_profile is not None:
        return user
    if user.role == UserRole.BUSINESS:
        m = user.staff_membership
        if m and m.is_active and m.staff_role == BusinessStaffRole.OWNER:
            return user
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Only the business owner can manage verification documents")
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account has no verification documents")


DocumentOwner = Annotated[User, Depends(require_document_owner)]


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def upload_document(
    db: DbSession,
    user: DocumentOwner,
    request: Request,
    document_type: Annotated[DocumentType, Form()],
    file: Annotated[UploadFile, File(description="JPEG, PNG or PDF, max 5 MB")],
) -> VerificationDocument:
    return documents.upload(db, user, document_type, file, request)


@router.get("", response_model=DocumentsOverview)
def my_documents(db: DbSession, user: DocumentOwner) -> DocumentsOverview:
    """Your uploads plus a checklist of what's still needed."""
    return documents.overview(db, user)


@router.get("/{document_id}/file")
def my_document_file(
    document_id: uuid.UUID, db: DbSession, user: DocumentOwner, request: Request
) -> Response:
    doc = db.get(VerificationDocument, document_id)
    # 404 (not 403) for other people's documents, so IDs can't be probed
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return documents.file_response(db, doc, user, request)
