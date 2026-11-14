import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.enums import HandoverKind, HandoverMethod, JobKind, JobStatus, OtpPurpose, VehicleType
from app.schemas.business import format_rands


class AvailabilityIn(BaseModel):
    is_available: bool


class AvailabilityOut(BaseModel):
    is_available: bool
    active_jobs: int


class PositionIn(BaseModel):
    """Driver's GPS position at the handover (SEC-022)."""

    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


Otp = Field(pattern=r"^\s*\d{6}\s*$", description="The customer's 6-digit code")
SealNumbers = Field(min_length=1, max_length=10,
                    description="Numbers on the tamper-evident seal(s) on the bag(s)")


class CollectIn(PositionIn):
    otp: str = Otp
    # SEC-026: seals the driver puts on the bag(s) at the customer's door
    seal_numbers: list[str] = SealNumbers


class PickupIn(PositionIn):
    code: str = Field(min_length=1, max_length=200, description="Scanned bag QR code")
    # Seals the laundry put on the clean bag(s)
    seal_numbers: list[str] = SealNumbers


class DeliverIn(PositionIn):
    otp: str = Otp
    # The customer checks the seals before accepting the bag (SEC-028)
    seals_intact: bool


class ReleaseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class JobBoardItem(BaseModel):
    """What a driver sees before accepting: no names, phone numbers or exact
    addresses (Business Rule 7)."""

    id: uuid.UUID
    kind: JobKind
    pickup_area: str
    dropoff_area: str
    distance_to_pickup_km: float
    trip_km: float
    window_start: datetime
    window_end: datetime
    driver_fee_cents: int
    item_count: int

    @computed_field
    @property
    def fee_display(self) -> str:
        return format_rands(self.driver_fee_cents)


class Stop(BaseModel):
    """One end of a trip. Contact details and exact address are only filled in
    while the job is active."""

    name: str
    area: str
    phone: str | None = None
    address_line: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    notes: str | None = None


class DriverJobOut(BaseModel):
    id: uuid.UUID
    kind: JobKind
    status: JobStatus
    order_number: str
    window_start: datetime
    window_end: datetime
    driver_fee_cents: int
    item_count: int
    pickup: Stop
    dropoff: Stop
    assigned_at: datetime | None
    picked_up_at: datetime | None
    completed_at: datetime | None
    # What the driver must do next, for the app's main button
    next_step: str | None


class HandoverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: HandoverKind
    method: HandoverMethod
    created_at: datetime
    location_flagged: bool
    distance_from_expected_m: float | None
    # Set when a failed seal check opened an incident at this handover
    incident_reference: str | None = None


class DriverInfoOut(BaseModel):
    """The driver currently handling the order, as the customer/business sees them."""

    first_name: str
    phone: str | None
    vehicle_type: VehicleType | None
    vehicle_registration: str | None
    job_kind: JobKind


class OtpOut(BaseModel):
    purpose: OtpPurpose
    code: str
    expires_at: datetime
