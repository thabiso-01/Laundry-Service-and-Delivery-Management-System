"""Public laundry search and business pages (UR-005, UR-006, UAT-002, UAT-003).

No login needed to browse – like a shop window. Ordering will require a
customer account (Business Rule 1). The searcher's location is used only for
the query and never stored.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import DbSession
from app.models import LaundryService, Review
from app.models.enums import ReviewTarget, ServiceCategory
from app.services import covers, reviews
from app.schemas.business import PublicServiceOut
from app.schemas.search import LaundryDetail, LaundrySearchItem, LaundrySearchPage, SortBy
from app.services import search as search_service

router = APIRouter(prefix="/api/laundries", tags=["laundries"])

Lat = Annotated[float, Query(ge=-90, le=90, description="Your latitude, e.g. -26.2041")]
Lng = Annotated[float, Query(ge=-180, le=180, description="Your longitude, e.g. 28.0473")]


@router.get("", response_model=LaundrySearchPage)
def search_laundries(
    db: DbSession,
    lat: Lat,
    lng: Lng,
    radius_km: Annotated[float, Query(gt=0, le=50)] = 10,
    category: ServiceCategory | None = None,
    q: Annotated[str | None, Query(max_length=100, description="Name, suburb or city")] = None,
    sort: SortBy = SortBy.DISTANCE,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LaundrySearchPage:
    """Approved laundries within `radius_km` that offer at least one (matching) service."""
    if sort == SortBy.PRICE and category is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Choose a service category to sort by price, so prices are comparable",
        )

    result = search_service.search(
        db, lat=lat, lng=lng, radius_km=radius_km, category=category,
        q=q or None, sort=sort, limit=limit, offset=offset,
    )
    items = [
        LaundrySearchItem(
            id=b.id,
            business_name=b.business_name,
            description=b.description,
            suburb=b.suburb,
            city=b.city,
            province=b.province,
            distance_km=round(km, 2),
            service_count=count,
            from_price_cents=price,
            fastest_turnaround_hours=fastest,
            rating_avg=round(float(rating_avg), 2) if rating_avg is not None else None,
            rating_count=rating_count,
            photo_url=covers.photo_url(b),
            matching_services=(
                [PublicServiceOut.model_validate(s) for s in result.services[b.id]]
                if category else None
            ),
        )
        for b, count, price, fastest, km, rating_avg, rating_count in result.rows
    ]
    return LaundrySearchPage(items=items, total=result.total, limit=limit, offset=offset,
                             radius_km=radius_km)


@router.get("/{business_id}", response_model=LaundryDetail)
def laundry_detail(
    business_id: uuid.UUID,
    db: DbSession,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
) -> LaundryDetail:
    """A business's public page with its active services. Pass lat/lng to get the distance."""
    business = search_service.get_bookable(db, business_id)
    if business is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Laundry not found")

    services = db.scalars(
        select(LaundryService)
        .where(LaundryService.business_id == business.id, LaundryService.is_active.is_(True))
        .order_by(LaundryService.category, LaundryService.price_cents)
    ).all()
    if not services:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Laundry not found")

    distance = None
    if lat is not None and lng is not None:
        distance = round(search_service.haversine_km(
            lat, lng, business.latitude, business.longitude), 2)

    return LaundryDetail(
        id=business.id,
        business_name=business.business_name,
        description=business.description,
        contact_phone=business.contact_phone,
        contact_email=business.contact_email,
        address_line=business.address_line,
        suburb=business.suburb,
        city=business.city,
        province=business.province,
        postal_code=business.postal_code,
        latitude=business.latitude,
        longitude=business.longitude,
        distance_km=distance,
        photo_url=covers.photo_url(business),
        services=[PublicServiceOut.model_validate(s) for s in services],
        **dict(zip(("rating_avg", "rating_count"), reviews.summary(
            db, Review.target == ReviewTarget.BUSINESS, Review.business_id == business.id))),
    )


@router.get("/{business_id}/photo", response_class=Response,
            responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}})
def laundry_photo(business_id: uuid.UUID, db: DbSession) -> Response:
    """The laundry's shop photo. Only approved laundries' photos are public."""
    business = search_service.get_bookable(db, business_id)
    if business is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Laundry not found")
    return covers.serve(business)
