"""Address search for the map pickers (checkout, registration, business profile).
Public, because laundries search for their address while registering;
rate-limited per IP."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.api.deps import DbSession
from app.config import settings
from app.core import ratelimit
from app.services import geocode

router = APIRouter(prefix="/api/geocode", tags=["address search"])


class AddressOut(BaseModel):
    label: str
    address_line: str
    suburb: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    latitude: float
    longitude: float


def _limit(request: Request, db: DbSession) -> None:
    ratelimit.check(request, db, "geocode", settings.geocoder_requests_per_minute_per_ip, 60,
                    "Too many address searches. Wait a minute and try again")


@router.get("", response_model=list[AddressOut])
def search_address(
    request: Request,
    db: DbSession,
    q: Annotated[str, Query(min_length=3, max_length=200, description="Street, suburb, place…")],
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
) -> list[dict]:
    """Suggestions for an address typed by the user (South Africa only)."""
    _limit(request, db)
    return geocode.search(q, limit)


@router.get("/reverse", response_model=AddressOut)
def reverse_lookup(
    request: Request,
    db: DbSession,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
) -> dict:
    """The address at a map position (after dragging the pin or 'use my location')."""
    _limit(request, db)
    found = geocode.reverse(lat, lng)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No address found at this spot")
    return found
