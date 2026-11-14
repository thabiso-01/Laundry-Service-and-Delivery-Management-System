"""Address search for the map pickers (checkout, registration, business profile).
Public, because laundries search for their address while registering;
rate-limited per IP."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

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


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=list[AddressOut])
def search_address(
    request: Request,
    q: Annotated[str, Query(min_length=3, max_length=200, description="Street, suburb, place…")],
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
) -> list[dict]:
    """Suggestions for an address typed by the user (South Africa only)."""
    geocode.check_rate_limit(_ip(request))
    return geocode.search(q, limit)


@router.get("/reverse", response_model=AddressOut)
def reverse_lookup(
    request: Request,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
) -> dict:
    """The address at a map position (after dragging the pin or 'use my location')."""
    geocode.check_rate_limit(_ip(request))
    found = geocode.reverse(lat, lng)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No address found at this spot")
    return found
