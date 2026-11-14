import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, computed_field, model_validator

from app.models.enums import JobKind, OrderStatus, PricingUnit, SealCheck, ServiceCategory
from app.schemas.business import UNIT_LABEL, format_rands
from app.schemas.driver import DriverInfoOut, HandoverOut


# ---------- Input ----------

class OrderAddress(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    address_line: str = Field(min_length=3, max_length=255)
    suburb: str | None = Field(default=None, max_length=100)
    city: str = Field(min_length=2, max_length=100)
    province: str | None = Field(default=None, max_length=50)
    postal_code: str | None = Field(default=None, max_length=10)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class TimeWindow(BaseModel):
    """Must include a timezone, e.g. 2026-11-16T09:00:00+02:00."""

    model_config = ConfigDict(extra="forbid")

    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("Window end must be after its start")
        return self


class OrderLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # no prices from the client, ever

    service_id: uuid.UUID
    quantity: int = Field(ge=1, le=100, description="kg, items or loads, per the service's unit")


class OrderIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    business_id: uuid.UUID
    items: list[OrderLineIn] = Field(min_length=1, max_length=20)
    collection_address: OrderAddress
    # Omit to deliver back to the collection address
    delivery_address: OrderAddress | None = None
    collection_window: TimeWindow
    delivery_window: TimeWindow
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def no_duplicate_services(self) -> Self:
        ids = [i.service_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each service may appear only once; adjust its quantity instead")
        return self


class CancelIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


# ---------- Output ----------

class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    service_id: uuid.UUID
    service_name: str
    category: ServiceCategory
    pricing_unit: PricingUnit
    unit_price_cents: int
    quantity: int
    line_total_cents: int

    @computed_field
    @property
    def description(self) -> str:
        unit = UNIT_LABEL[self.pricing_unit.value].removeprefix("per ")
        return f"{self.quantity} {unit} × {format_rands(self.unit_price_cents)}"


class QuoteOut(BaseModel):
    items: list[LineOut]
    subtotal_cents: int
    delivery_fee_cents: int
    total_cents: int
    distance_km: float
    is_estimate: bool
    earliest_delivery: datetime

    @computed_field
    @property
    def total_display(self) -> str:
        return format_rands(self.total_cents) + (" (estimate)" if self.is_estimate else "")


class StatusEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: OrderStatus | None
    to_status: OrderStatus
    note: str | None
    created_at: datetime


class AddressOut(BaseModel):
    address_line: str
    suburb: str | None
    city: str
    province: str | None
    postal_code: str | None
    latitude: float
    longitude: float


class OrderSummaryOut(BaseModel):
    id: uuid.UUID
    order_number: str
    status: OrderStatus
    business_id: uuid.UUID
    business_name: str
    total_cents: int
    is_estimate: bool
    collection_window_start: datetime
    collection_window_end: datetime
    delivery_window_start: datetime
    delivery_window_end: datetime
    created_at: datetime


class OrderOut(OrderSummaryOut):
    items: list[LineOut]
    subtotal_cents: int
    delivery_fee_cents: int
    distance_km: float
    collection_address: AddressOut
    delivery_address: AddressOut
    notes: str | None
    cancelled_reason: str | None
    declined_reason: str | None
    history: list[StatusEventOut]
    # The driver on the way right now, if any (UR-012)
    driver: DriverInfoOut | None = None
    # Verified handovers so far (SEC-013 – SEC-016)
    handovers: list[HandoverOut] = []
    # Tamper-evident seals on the bag(s) (SEC-025)
    seals: list["SealOut"] = []
    # Money after placing: payments received and the weighing adjustment
    paid_cents: int = 0
    adjustment_cents: int = 0
    final_total_cents: int = 0
    # > 0: still to pay; < 0: refund due to the customer
    balance_cents: int = 0
    # The driver trips for this order (to rate each driver after delivery)
    trips: list["TripOut"] = []


class TripOut(BaseModel):
    job_id: uuid.UUID
    kind: JobKind
    status: str
    driver_first_name: str | None


# ---------- Business side ----------

class DeclineIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # Shown to the customer
    reason: str = Field(min_length=5, max_length=500)


class StatusChangeIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    status: Literal[OrderStatus.PROCESSING, OrderStatus.READY]
    note: str | None = Field(default=None, max_length=500)


class StaffEventOut(StatusEventOut):
    """History entry including who made the change (SEC-017)."""

    actor_name: str | None
    actor_role: str | None


class BusinessOrderOut(OrderOut):
    customer_name: str
    customer_phone: str | None
    history: list[StaffEventOut]  # type: ignore[assignment]
    # Set when receiving the bag failed its seal check and an incident was opened
    seal_incident_reference: str | None = None


class StatusCounts(BaseModel):
    counts: dict[OrderStatus, int]


class ReceiveIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: str = Field(min_length=1, max_length=200, description="Scanned bag QR code")
    # SEC-027: the seal numbers staff can see on the bag(s), and whether they look untouched
    seal_numbers: list[str] = Field(default_factory=list, max_length=10)
    seals_intact: bool


class SealOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seal_number: str
    leg: JobKind
    check_result: SealCheck | None
    recorded_at: datetime


class OrderPage(BaseModel):
    items: list[OrderSummaryOut]
    total: int
    limit: int
    offset: int


# SealOut is defined after OrderOut; resolve the forward reference
OrderOut.model_rebuild()
BusinessOrderOut.model_rebuild()
