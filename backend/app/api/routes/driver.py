"""The driver app: availability, job board, my jobs and handovers
(UR-009, SEC-004, SEC-007, SEC-011, SEC-013 – SEC-016, SEC-022, Business Rule 7).

Every route requires an admin-approved driver (SEC-004).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import ApprovedDriver, DbSession
from app.config import settings
from app.models import DeliveryJob, Order
from app.models.enums import JobKind, JobStatus
from app.schemas.driver import (
    AvailabilityIn,
    AvailabilityOut,
    CollectIn,
    DeliverIn,
    DriverJobOut,
    HandoverOut,
    JobBoardItem,
    PickupIn,
    ReleaseIn,
    Stop,
)
from app.services import audit, jobs
from app.services.search import haversine_km

router = APIRouter(prefix="/api/driver", tags=["driver"])

DONE = (JobStatus.COMPLETED, JobStatus.CANCELLED)


def _area(suburb: str | None, city: str | None) -> str:
    return ", ".join(p for p in (suburb, city) if p) or "Unknown area"


def _first_name(full_name: str) -> str:
    return full_name.split()[0] if full_name.strip() else full_name


def _stops(job: DeliveryJob) -> tuple[Stop, Stop]:
    o, b = job.order, job.order.business
    active = job.status in jobs.ACTIVE_JOB
    customer_addr = ("collection" if job.kind == JobKind.COLLECTION else "delivery")

    def customer() -> Stop:
        stop = Stop(name=_first_name(o.customer.full_name),
                    area=_area(getattr(o, f"{customer_addr}_suburb"),
                               getattr(o, f"{customer_addr}_city")))
        if active:  # Business Rule 7: only while the driver needs it
            stop.phone = o.customer.phone
            stop.address_line = getattr(o, f"{customer_addr}_address_line")
            stop.latitude = getattr(o, f"{customer_addr}_latitude")
            stop.longitude = getattr(o, f"{customer_addr}_longitude")
            stop.notes = o.customer_notes
        return stop

    laundry = Stop(name=b.business_name, area=_area(b.suburb, b.city), phone=b.contact_phone,
                   address_line=b.address_line, latitude=b.latitude, longitude=b.longitude)
    return (customer(), laundry) if job.kind == JobKind.COLLECTION else (laundry, customer())


_NEXT = {
    (JobKind.COLLECTION, JobStatus.ASSIGNED): "Collect from customer: enter their collection code",
    (JobKind.COLLECTION, JobStatus.PICKED_UP): "Drop off at the laundry: staff will scan the bag",
    (JobKind.DELIVERY, JobStatus.ASSIGNED): "Pick up at the laundry: scan the bag's QR code",
    (JobKind.DELIVERY, JobStatus.PICKED_UP): "Deliver to customer: enter their delivery code",
}


def job_out(job: DeliveryJob) -> DriverJobOut:
    pickup, dropoff = _stops(job)
    start, end = jobs.window(job)
    return DriverJobOut(
        id=job.id, kind=job.kind, status=job.status, order_number=job.order.order_number,
        window_start=start, window_end=end, driver_fee_cents=job.driver_fee_cents,
        item_count=len(job.order.items), pickup=pickup, dropoff=dropoff,
        assigned_at=job.assigned_at, picked_up_at=job.picked_up_at,
        completed_at=job.completed_at, next_step=_NEXT.get((job.kind, job.status)),
    )


def _my_job(db: DbSession, driver: ApprovedDriver, job_id: uuid.UUID,
            lock: bool = False) -> DeliveryJob:
    job = db.get(DeliveryJob, job_id, with_for_update=lock)
    if job is None or job.driver_id != driver.user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if lock:
        db.get(Order, job.order_id, with_for_update=True)
    return job


def _position(body) -> tuple[float, float]:
    return body.latitude, body.longitude


# ---------- Availability ----------

@router.patch("/availability", response_model=AvailabilityOut)
def set_availability(
    body: AvailabilityIn, driver: ApprovedDriver, db: DbSession, request: Request
) -> AvailabilityOut:
    """Go online to see and accept jobs, or offline to stop receiving new ones.
    Jobs you already have stay with you."""
    if driver.is_available != body.is_available:
        driver.is_available = body.is_available
        audit.record(db, "driver.online" if body.is_available else "driver.offline",
                     actor_id=driver.user_id, request=request)
        db.commit()
    active = db.scalar(select(func.count()).select_from(DeliveryJob).where(
        DeliveryJob.driver_id == driver.user_id, DeliveryJob.status.in_(jobs.ACTIVE_JOB)))
    return AvailabilityOut(is_available=driver.is_available, active_jobs=active)


# ---------- Job board ----------

@router.get("/jobs/available", response_model=list[JobBoardItem])
def available_jobs(
    driver: ApprovedDriver,
    db: DbSession,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    radius_km: Annotated[float, Query(gt=0, le=50)] = settings.driver_board_default_radius_km,
) -> list[JobBoardItem]:
    """Open jobs near you, closest pickup first. Your location isn't stored."""
    if not driver.is_available:
        raise HTTPException(status.HTTP_409_CONFLICT, "Go online to see available jobs")

    # Hide jobs whose time window ended over an hour ago
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    open_jobs = db.scalars(select(DeliveryJob).where(DeliveryJob.status == JobStatus.OPEN))
    items = []
    for job in open_jobs:
        start, end = jobs.window(job)
        if end < cutoff:
            continue
        pickup, dropoff = jobs.pickup_point(job), jobs.dropoff_point(job)
        distance = haversine_km(lat, lng, *pickup)
        if distance > radius_km:
            continue
        p, d = _stops(job)
        items.append(JobBoardItem(
            id=job.id, kind=job.kind, pickup_area=p.area, dropoff_area=d.area,
            distance_to_pickup_km=round(distance, 2),
            trip_km=round(haversine_km(*pickup, *dropoff), 2),
            window_start=start, window_end=end, driver_fee_cents=job.driver_fee_cents,
            item_count=len(job.order.items),
        ))
    return sorted(items, key=lambda i: (i.distance_to_pickup_km, i.window_start))[:50]


@router.post("/jobs/{job_id}/accept", response_model=DriverJobOut)
def accept_job(
    job_id: uuid.UUID, driver: ApprovedDriver, db: DbSession, request: Request
) -> DriverJobOut:
    """First driver to accept gets the job; everyone else gets 409."""
    # Row lock: two drivers tapping "accept" at once can't both win
    job = db.get(DeliveryJob, job_id, with_for_update=True)
    if job is None or job.status == JobStatus.CANCELLED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    jobs.accept(db, job, driver.user, request)
    return job_out(job)


# ---------- My jobs ----------

@router.get("/jobs", response_model=list[DriverJobOut])
def my_jobs(
    driver: ApprovedDriver, db: DbSession,
    include_finished: Annotated[bool, Query()] = False,
) -> list[DriverJobOut]:
    query = select(DeliveryJob).where(DeliveryJob.driver_id == driver.user_id)
    if not include_finished:
        query = query.where(DeliveryJob.status.not_in(DONE))
    rows = db.scalars(query.order_by(DeliveryJob.assigned_at.desc()).limit(100))
    return [job_out(j) for j in rows]


@router.get("/jobs/{job_id}", response_model=DriverJobOut)
def get_job(job_id: uuid.UUID, driver: ApprovedDriver, db: DbSession) -> DriverJobOut:
    return job_out(_my_job(db, driver, job_id))


@router.post("/jobs/{job_id}/release", response_model=DriverJobOut)
def release_job(
    job_id: uuid.UUID, body: ReleaseIn, driver: ApprovedDriver, db: DbSession, request: Request
) -> DriverJobOut:
    """Give a job back (before picking up the laundry) so another driver can take it."""
    job = _my_job(db, driver, job_id, lock=True)
    jobs.release(db, job, driver.user, body.reason, request)
    return job_out(job)


# ---------- Handovers ----------

@router.post("/jobs/{job_id}/collect", response_model=HandoverOut)
def collect(
    job_id: uuid.UUID, body: CollectIn, driver: ApprovedDriver, db: DbSession,
    request: Request,
) -> HandoverOut:
    """At the customer's door: seal the bag(s), record the seal numbers and
    enter the collection code the customer gives you (UAT-007)."""
    job = _my_job(db, driver, job_id, lock=True)
    return HandoverOut.model_validate(jobs.collect(
        db, job, driver.user, body.otp, _position(body), body.seal_numbers, request))


@router.post("/jobs/{job_id}/pickup", response_model=HandoverOut)
def pickup(
    job_id: uuid.UUID, body: PickupIn, driver: ApprovedDriver, db: DbSession,
    request: Request,
) -> HandoverOut:
    """At the laundry: scan the clean bag's QR code and record its seal numbers."""
    job = _my_job(db, driver, job_id, lock=True)
    return HandoverOut.model_validate(jobs.pickup(
        db, job, driver.user, body.code, _position(body), body.seal_numbers, request))


@router.post("/jobs/{job_id}/deliver", response_model=HandoverOut)
def deliver(
    job_id: uuid.UUID, body: DeliverIn, driver: ApprovedDriver, db: DbSession,
    request: Request,
) -> HandoverOut:
    """At the customer's door: the customer checks the seals, then gives you
    their delivery code (UAT-011). Broken seals open an incident automatically."""
    job = _my_job(db, driver, job_id, lock=True)
    record, incident = jobs.deliver(db, job, driver.user, body.otp, _position(body),
                                    body.seals_intact, request)
    out = HandoverOut.model_validate(record)
    out.incident_reference = incident.reference if incident else None
    return out
