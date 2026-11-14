"""Live tracking (SEC-021 – SEC-024, UAT-010)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import ApprovedDriver, CustomerUser, DbSession, require_admin
from app.api.routes.driver import _my_job
from app.api.routes.orders import _own_order
from app.models import DeliveryJob, DriverLocation, Order
from app.schemas.engagement import (
    DeviationOut,
    JobRouteOut,
    LocationIn,
    PingOut,
    RoutePointOut,
    TrackingOut,
)
from app.services import jobs, tracking
from app.services.search import haversine_km

router = APIRouter(tags=["tracking"])


@router.post("/api/driver/jobs/{job_id}/location", response_model=PingOut)
def send_location(job_id: uuid.UUID, body: LocationIn, driver: ApprovedDriver, db: DbSession,
                  request: Request) -> PingOut:
    """The driver app sends its position every ~15 s during an active job."""
    job = _my_job(db, driver, job_id)
    if job.status not in jobs.ACTIVE_JOB:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tracking only runs during an active job")
    loc = tracking.ping(db, job, driver.user, body.latitude, body.longitude, request)
    return PingOut(accepted=loc is not None, off_route=bool(loc and loc.off_route))


@router.get("/api/orders/{order_id}/tracking", response_model=TrackingOut)
def track_order(order_id: uuid.UUID, customer: CustomerUser, db: DbSession) -> TrackingOut:
    """Where your driver is right now (UAT-010). Only while a driver is on a
    trip for your order – never before or after."""
    order = _own_order(db, customer, order_id)
    job = next((j for j in order.jobs if j.status in jobs.ACTIVE_JOB and j.driver), None)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No driver is on the way right now")
    loc = tracking.latest(db, job)
    dest = jobs.pickup_point(job) if job.status.value == "assigned" else jobs.dropoff_point(job)
    return TrackingOut(
        job_kind=job.kind,
        driver_first_name=job.driver.full_name.split()[0],
        latitude=loc.latitude if loc else None,
        longitude=loc.longitude if loc else None,
        recorded_at=loc.recorded_at if loc else None,
        is_live=bool(loc and tracking.is_fresh(loc)),
        distance_to_destination_km=round(haversine_km(loc.latitude, loc.longitude, *dest), 2)
        if loc else None,
    )


# ---------- Admin: route review (SEC-023, SEC-024) ----------

admin = APIRouter(prefix="/api/admin", tags=["admin: tracking"],
                  dependencies=[Depends(require_admin)])


@admin.get("/orders/{order_id}/route", response_model=list[JobRouteOut])
def order_route(order_id: uuid.UUID, db: DbSession) -> list[JobRouteOut]:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    out = []
    for job in order.jobs:
        points = tracking.route(db, job)
        out.append(JobRouteOut(
            job_id=job.id, kind=job.kind,
            driver_name=job.driver.full_name if job.driver else None,
            points=[RoutePointOut.model_validate(p) for p in points],
            off_route_points=sum(p.off_route for p in points),
        ))
    return out


@admin.get("/route-deviations", response_model=list[DeviationOut])
def route_deviations(
    db: DbSession, limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[DeviationOut]:
    """Trips where a driver carrying laundry went well off the direct route."""
    rows = db.execute(
        select(DriverLocation.job_id, func.count(), func.min(DriverLocation.recorded_at))
        .where(DriverLocation.off_route.is_(True))
        .group_by(DriverLocation.job_id)
        .order_by(func.min(DriverLocation.recorded_at).desc()).limit(limit)
    ).all()
    out = []
    for job_id, count, first_seen in rows:
        job = db.get(DeliveryJob, job_id)
        out.append(DeviationOut(
            job_id=job.id, order_id=job.order_id, order_number=job.order.order_number,
            kind=job.kind, driver_name=job.driver.full_name if job.driver else None,
            off_route_points=count, first_seen=first_seen,
        ))
    return out
