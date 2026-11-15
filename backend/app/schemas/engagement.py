import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import JobKind, PaymentStatus, ReviewTarget


# ---------- Payments ----------

class CheckoutOut(BaseModel):
    payment_id: uuid.UUID
    provider: str
    reference: str
    amount_cents: int
    amount_display: str
    checkout_url: str
    # PayFast: the browser POSTs form_fields (in this order) to form_action
    form_action: str | None = None
    form_fields: list[tuple[str, str]] | None = None


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    status: PaymentStatus
    amount_cents: int
    created_at: datetime
    paid_at: datetime | None


class SandboxResultIn(BaseModel):
    outcome: Literal["paid", "failed"] = "paid"


class WeighLineIn(BaseModel):
    service_id: uuid.UUID
    actual_quantity: int = Field(ge=1, le=200, description="Weighed kilograms, rounded up")


class WeighIn(BaseModel):
    lines: list[WeighLineIn] = Field(min_length=1, max_length=20)


# ---------- Notifications ----------

class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    body: str
    order_id: uuid.UUID | None
    incident_id: uuid.UUID | None
    read_at: datetime | None
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    unread: int


# ---------- Tracking ----------

class LocationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class PingOut(BaseModel):
    accepted: bool  # false when sent sooner than the minimum interval
    off_route: bool = False


class TrackingOut(BaseModel):
    job_kind: JobKind
    driver_first_name: str
    latitude: float | None
    longitude: float | None
    recorded_at: datetime | None
    is_live: bool
    distance_to_destination_km: float | None


class RoutePointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    latitude: float
    longitude: float
    off_route: bool
    recorded_at: datetime


class JobRouteOut(BaseModel):
    job_id: uuid.UUID
    kind: JobKind
    driver_name: str | None
    points: list[RoutePointOut]
    off_route_points: int


class DeviationOut(BaseModel):
    job_id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    kind: JobKind
    driver_name: str | None
    off_route_points: int
    first_seen: datetime


# ---------- Reviews ----------

class ReviewIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    target: ReviewTarget
    job_id: uuid.UUID | None = Field(default=None, description="Which trip, for a driver review")
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class ReviewOut(BaseModel):
    """Public review: the customer's first name only."""

    id: uuid.UUID
    target: ReviewTarget
    rating: int
    comment: str | None
    reviewer: str
    created_at: datetime


class RatingSummaryOut(BaseModel):
    rating_avg: float | None
    rating_count: int


class DriverRatingsOut(RatingSummaryOut):
    recent: list[ReviewOut]


class HideReviewIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)
