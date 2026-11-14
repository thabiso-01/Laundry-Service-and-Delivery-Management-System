import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import VehicleType, VerificationStatus


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class RejectIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # Shown to the driver/business so they know what to fix
    reason: str = Field(min_length=5, max_length=1000)


class DriverReviewOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    email: str
    phone: str | None
    id_number: str
    vehicle_type: VehicleType | None
    vehicle_registration: str | None
    verification_status: VerificationStatus
    verified_at: datetime | None
    verified_by_id: uuid.UUID | None
    rejection_reason: str | None
    registered_at: datetime


class BusinessReviewOut(BaseModel):
    id: uuid.UUID
    business_name: str
    registration_number: str | None
    description: str | None
    contact_phone: str | None
    contact_email: str | None
    address_line: str | None
    suburb: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    owner_user_id: uuid.UUID
    owner_name: str
    owner_email: str
    verification_status: VerificationStatus
    verified_at: datetime | None
    verified_by_id: uuid.UUID | None
    rejection_reason: str | None
    registered_at: datetime
