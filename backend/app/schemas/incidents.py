import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    HandoverKind,
    HandoverMethod,
    IncidentCategory,
    IncidentSeverity,
    IncidentStatus,
    OrderStatus,
    PhotoStage,
    UserRole,
)
from app.schemas.orders import SealOut, StaffEventOut


class IncidentIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    order_id: uuid.UUID | None = None
    category: IncidentCategory
    description: str = Field(min_length=10, max_length=2000,
                             description="What happened, which items, and when")


class CommentIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    note: str = Field(min_length=1, max_length=2000)
    # Admins only: hidden from the reporter
    internal: bool = False


class StatusIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    status: IncidentStatus
    note: str | None = Field(default=None, max_length=2000)
    # Required when resolving or dismissing (SEC-037)
    resolution: str | None = Field(default=None, min_length=5, max_length=2000)


class SeverityIn(BaseModel):
    severity: IncidentSeverity


class SuspendIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    reason: str = Field(min_length=5, max_length=500)
    incident_id: uuid.UUID | None = None


class UpdateOut(BaseModel):
    from_status: IncidentStatus | None
    to_status: IncidentStatus | None
    note: str | None
    internal: bool
    author: str
    created_at: datetime


class IncidentSummaryOut(BaseModel):
    id: uuid.UUID
    reference: str
    order_number: str | None
    category: IncidentCategory
    status: IncidentStatus
    severity: IncidentSeverity
    is_automatic: bool
    created_at: datetime


class IncidentOut(IncidentSummaryOut):
    order_id: uuid.UUID | None
    description: str
    resolution: str | None
    closed_at: datetime | None
    updates: list[UpdateOut]


class PhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID | None
    incident_id: uuid.UUID | None
    stage: PhotoStage
    uploader_role: UserRole
    caption: str | None
    content_type: str
    file_size: int
    created_at: datetime


class HandoverDetailOut(BaseModel):
    """Full handover record for investigators, including GPS (SEC-023)."""

    kind: HandoverKind
    method: HandoverMethod
    created_at: datetime
    from_name: str | None
    to_name: str | None
    latitude: float | None
    longitude: float | None
    distance_from_expected_m: float | None
    location_flagged: bool


class EvidenceOut(BaseModel):
    """Everything recorded about the order, gathered for the investigation."""

    order_id: uuid.UUID
    order_number: str
    order_status: OrderStatus
    business_name: str
    customer_name: str
    history: list[StaffEventOut]
    handovers: list[HandoverDetailOut]
    seals: list[SealOut]
    photos: list[PhotoOut]


class AdminIncidentOut(IncidentOut):
    reporter_id: uuid.UUID
    reporter_name: str
    reporter_role: UserRole
    assigned_admin_name: str | None
    evidence: EvidenceOut | None
    incident_photos: list[PhotoOut]


class IncidentPage(BaseModel):
    items: list[IncidentSummaryOut]
    total: int
    limit: int
    offset: int
