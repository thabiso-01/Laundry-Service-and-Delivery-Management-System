import uuid
from enum import StrEnum

from pydantic import BaseModel, computed_field

from app.schemas.business import PublicServiceOut, format_rands


class SortBy(StrEnum):
    DISTANCE = "distance"
    PRICE = "price"  # requires a category, so like is compared with like
    TURNAROUND = "turnaround"
    RATING = "rating"  # best rated first; unrated laundries last


class LaundrySearchItem(BaseModel):
    id: uuid.UUID
    business_name: str
    description: str | None
    suburb: str | None
    city: str | None
    province: str | None
    distance_km: float
    service_count: int
    # Cheapest / fastest among the services that match the search
    from_price_cents: int
    fastest_turnaround_hours: int
    rating_avg: float | None = None
    rating_count: int = 0
    photo_url: str | None = None
    # Filled in when searching by category, so customers can compare (UR-006)
    matching_services: list[PublicServiceOut] | None = None

    @computed_field
    @property
    def from_price_display(self) -> str:
        return f"from {format_rands(self.from_price_cents)}"


class LaundrySearchPage(BaseModel):
    items: list[LaundrySearchItem]
    total: int
    limit: int
    offset: int
    radius_km: float


class LaundryDetail(BaseModel):
    """Public business page. Deliberately excludes owner and verification details."""

    id: uuid.UUID
    business_name: str
    description: str | None
    contact_phone: str | None
    contact_email: str | None
    address_line: str | None
    suburb: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    latitude: float
    longitude: float
    distance_km: float | None
    photo_url: str | None = None
    services: list[PublicServiceOut]
    rating_avg: float | None = None
    rating_count: int = 0
