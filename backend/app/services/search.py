"""Find nearby laundries (UR-005) and compare their services (UR-006).

Distance uses the haversine formula in SQL. A cheap bounding-box filter runs
first so the trigonometry only happens for businesses that are roughly close.
Good for thousands of businesses; move to PostGIS if the platform grows past that.
"""

import math
import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import ColumnElement, Select, and_, func, literal, or_, select
from sqlalchemy.orm import Session

from app.models import BusinessProfile, LaundryService, User
from app.models.enums import AccountStatus, ServiceCategory, VerificationStatus
from app.schemas.search import SortBy
from app.services.reviews import business_rating_subquery

EARTH_RADIUS_KM = 6371.0
KM_PER_DEGREE_LAT = 111.32


def distance_km(lat: float, lng: float) -> ColumnElement[float]:
    """SQL expression: km from (lat, lng) to each business."""
    lat1, lng1 = math.radians(lat), math.radians(lng)
    lat2 = func.radians(BusinessProfile.latitude)
    lng2 = func.radians(BusinessProfile.longitude)
    a = (
        func.power(func.sin((lat2 - lat1) / 2), 2)
        + math.cos(lat1) * func.cos(lat2) * func.power(func.sin((lng2 - lng1) / 2), 2)
    )
    # least(1, …) guards against rounding pushing asin's input just over 1
    return 2 * EARTH_RADIUS_KM * func.asin(func.sqrt(func.least(literal(1.0), a)))


def bookable() -> ColumnElement[bool]:
    """A business customers may see: verified (SEC-043), on the map, and its
    owner's account not suspended (SEC-044)."""
    return and_(
        BusinessProfile.verification_status == VerificationStatus.APPROVED,
        BusinessProfile.latitude.is_not(None),
        BusinessProfile.longitude.is_not(None),
        User.status == AccountStatus.ACTIVE,
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass
class SearchResult:
    # business, service count, from price, fastest, km, rating avg, rating count
    rows: list[tuple[BusinessProfile, int, int, int, float, float | None, int]]
    total: int
    services: dict[uuid.UUID, list[LaundryService]]


def search(
    db: Session,
    *,
    lat: float,
    lng: float,
    radius_km: float,
    category: ServiceCategory | None,
    q: str | None,
    sort: SortBy,
    limit: int,
    offset: int,
) -> SearchResult:
    # Per-business summary of the active services that match the filter
    svc_filter = [LaundryService.is_active.is_(True)]
    if category:
        svc_filter.append(LaundryService.category == category)
    svc = (
        select(
            LaundryService.business_id,
            func.count().label("service_count"),
            func.min(LaundryService.price_cents).label("from_price"),
            func.min(LaundryService.turnaround_hours).label("fastest"),
        )
        .where(*svc_filter)
        .group_by(LaundryService.business_id)
        .subquery()
    )

    dist = distance_km(lat, lng).label("distance_km")
    dlat = radius_km / KM_PER_DEGREE_LAT
    dlng = radius_km / (KM_PER_DEGREE_LAT * max(math.cos(math.radians(lat)), 0.01))

    where = [
        bookable(),
        BusinessProfile.latitude.between(lat - dlat, lat + dlat),
        BusinessProfile.longitude.between(lng - dlng, lng + dlng),
        dist <= radius_km,
    ]
    if q:
        pattern = f"%{_escape_like(q.strip())}%"
        where.append(or_(
            BusinessProfile.business_name.ilike(pattern, escape="\\"),
            BusinessProfile.suburb.ilike(pattern, escape="\\"),
            BusinessProfile.city.ilike(pattern, escape="\\"),
        ))

    ratings = business_rating_subquery()
    base: Select = (
        select(BusinessProfile, svc.c.service_count, svc.c.from_price, svc.c.fastest, dist,
               ratings.c.rating_avg, func.coalesce(ratings.c.rating_count, 0))
        .join(svc, svc.c.business_id == BusinessProfile.id)  # inner join: no services → hidden
        .join(User, User.id == BusinessProfile.owner_user_id)
        .outerjoin(ratings, ratings.c.business_id == BusinessProfile.id)
        .where(*where)
    )

    total = db.scalar(select(func.count()).select_from(base.subquery()))

    order = {
        SortBy.DISTANCE: [dist],
        SortBy.PRICE: [svc.c.from_price, dist],
        SortBy.TURNAROUND: [svc.c.fastest, dist],
        SortBy.RATING: [ratings.c.rating_avg.desc().nulls_last(), dist],
    }[sort]
    rows = db.execute(base.order_by(*order, BusinessProfile.id).limit(limit).offset(offset)).all()

    services: dict[uuid.UUID, list[LaundryService]] = defaultdict(list)
    if category and rows:
        for s in db.scalars(
            select(LaundryService)
            .where(
                LaundryService.business_id.in_([r[0].id for r in rows]),
                *svc_filter,
            )
            .order_by(LaundryService.price_cents, LaundryService.name)
        ):
            services[s.business_id].append(s)

    return SearchResult(rows=[tuple(r) for r in rows], total=total, services=services)


def get_bookable(db: Session, business_id: uuid.UUID) -> BusinessProfile | None:
    return db.scalar(
        select(BusinessProfile)
        .join(User, User.id == BusinessProfile.owner_user_id)
        .where(BusinessProfile.id == business_id, bookable())
    )


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Python version, for a single business page."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))
