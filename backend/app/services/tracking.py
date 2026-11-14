"""Live driver location during active jobs (SEC-021 – SEC-024).

* drivers send pings only while a job is active; customers see the latest
  one, and only while that job is active (privacy: no tracking off the clock);
* while the driver is carrying laundry, a ping well outside the direct route
  (the ellipse around pickup and drop-off) is flagged off-route (SEC-024);
* admins can replay the whole route when investigating (SEC-023).
"""

from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import DeliveryJob, DriverLocation, User
from app.models.enums import JobStatus
from app.services import audit, jobs
from app.services.search import haversine_km


def is_off_route(job: DeliveryJob, lat: float, lng: float) -> bool:
    """Outside the ellipse whose foci are pickup and drop-off: the detour via
    this point is more than `route_deviation_km` × 2 longer than going direct."""
    a, b = jobs.pickup_point(job), jobs.dropoff_point(job)
    direct = haversine_km(*a, *b)
    via = haversine_km(*a, lat, lng) + haversine_km(lat, lng, *b)
    return via > direct + 2 * settings.route_deviation_km


def latest(db: Session, job: DeliveryJob) -> DriverLocation | None:
    return db.scalar(select(DriverLocation).where(DriverLocation.job_id == job.id)
                     .order_by(DriverLocation.recorded_at.desc()).limit(1))


def ping(db: Session, job: DeliveryJob, driver: User, lat: float, lng: float,
         request: Request) -> DriverLocation | None:
    """Stores a position. Returns None when ignored because it came too soon."""
    now = datetime.now(UTC)
    last = latest(db, job)
    if last and now - last.recorded_at < timedelta(seconds=settings.location_ping_min_seconds):
        return None
    off_route = job.status == JobStatus.PICKED_UP and is_off_route(job, lat, lng)
    # Check for earlier deviations BEFORE adding this ping (autoflush would find it)
    first_deviation = off_route and db.scalar(select(DriverLocation.id).where(
        DriverLocation.job_id == job.id, DriverLocation.off_route.is_(True)).limit(1)) is None
    location = DriverLocation(job_id=job.id, driver_id=driver.id, latitude=lat, longitude=lng,
                              off_route=off_route, recorded_at=now)
    db.add(location)
    if off_route:
        if first_deviation:  # log the first deviation of the trip, not every ping
            audit.record(db, "job.route_deviation", actor_id=driver.id,
                         entity_type="delivery_job", entity_id=job.id,
                         details={"order_number": job.order.order_number,
                                  "latitude": lat, "longitude": lng},
                         request=request)
    db.commit()
    return location


def is_fresh(location: DriverLocation) -> bool:
    return datetime.now(UTC) - location.recorded_at <= timedelta(
        minutes=settings.tracking_stale_minutes)


def route(db: Session, job: DeliveryJob) -> list[DriverLocation]:
    return list(db.scalars(select(DriverLocation).where(DriverLocation.job_id == job.id)
                           .order_by(DriverLocation.recorded_at)))
