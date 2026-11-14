import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DocumentType, VerificationStatus


class DocumentOut(BaseModel):
    """Document metadata. The file itself is fetched from the /file endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_type: DocumentType
    original_filename: str
    content_type: str
    file_size: int
    status: VerificationStatus
    review_notes: str | None
    uploaded_at: datetime
    reviewed_at: datetime | None


class RequirementOut(BaseModel):
    name: str
    accepted_types: list[DocumentType]
    status: Literal["missing", "pending", "approved", "rejected"]
    document_id: uuid.UUID | None
    notes: str | None


class DocumentsOverview(BaseModel):
    documents: list[DocumentOut]
    requirements: list[RequirementOut]
    # True once every requirement is uploaded (approved or awaiting review)
    ready_for_review: bool
    # True once every requirement is approved, i.e. the account can be approved
    all_approved: bool


class AdminDocumentOut(DocumentOut):
    user_id: uuid.UUID
    owner_name: str
    owner_role: str


class ApproveDocumentIn(BaseModel):
    notes: str | None = Field(default=None, max_length=1000)
