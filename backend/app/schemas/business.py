import uuid
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    computed_field,
    model_validator,
)

from app.models.enums import PricingUnit, ServiceCategory, VerificationStatus
from app.schemas.validators import normalise_sa_phone

SAPhone = Annotated[str, AfterValidator(normalise_sa_phone)]
# Up to R10 000 per unit; stops typos like 850000 instead of 8500
PriceCents = Annotated[int, Field(gt=0, le=1_000_000, description="Price in cents, R85.50 = 8550")]


def format_rands(cents: int) -> str:
    return f"R{cents / 100:,.2f}".replace(",", " ")  # SA style: R1 250.00


# ---------- Business profile ----------

class BusinessProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    latitude: float | None
    longitude: float | None
    verification_status: VerificationStatus
    rejection_reason: str | None
    photo_url: str | None = None


class BusinessProfileUpdate(BaseModel):
    """Only the fields sent are changed. The CIPC registration number can't be
    changed here because it was checked during verification."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    business_name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    contact_phone: SAPhone | None = None
    contact_email: EmailStr | None = None
    address_line: str | None = Field(default=None, max_length=255)
    suburb: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    province: str | None = Field(default=None, max_length=50)
    postal_code: str | None = Field(default=None, max_length=10)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def coordinates_together(self) -> Self:
        sent = self.model_fields_set
        if ("latitude" in sent) != ("longitude" in sent):
            raise ValueError("Send latitude and longitude together")
        if "business_name" in sent and self.business_name is None:
            raise ValueError("business_name cannot be empty")
        return self


# ---------- Services ----------

class ServiceIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    category: ServiceCategory
    pricing_unit: PricingUnit
    price_cents: PriceCents
    min_quantity: int = Field(default=1, ge=1, le=1000)
    turnaround_hours: int = Field(ge=1, le=720, description="Up to 30 days")


class ServiceUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    category: ServiceCategory | None = None
    pricing_unit: PricingUnit | None = None
    price_cents: PriceCents | None = None
    min_quantity: int | None = Field(default=None, ge=1, le=1000)
    turnaround_hours: int | None = Field(default=None, ge=1, le=720)
    is_active: bool | None = None

    @model_validator(mode="after")
    def no_nulls_for_required(self) -> Self:
        for field in ("name", "category", "pricing_unit", "price_cents",
                      "min_quantity", "turnaround_hours", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be empty")
        return self


UNIT_LABEL = {"per_kg": "per kg", "per_item": "per item", "per_load": "per load"}


class PublicServiceOut(BaseModel):
    """A service as customers see it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    category: ServiceCategory
    pricing_unit: PricingUnit
    price_cents: int
    min_quantity: int
    turnaround_hours: int

    @computed_field
    @property
    def price_display(self) -> str:
        return f"{format_rands(self.price_cents)} {UNIT_LABEL[self.pricing_unit.value]}"


class ServiceOut(PublicServiceOut):
    """A service as the business's own staff see it."""

    is_active: bool
