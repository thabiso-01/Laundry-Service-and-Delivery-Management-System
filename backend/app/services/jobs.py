"""Driver jobs and the four verified handovers (UR-009, SEC-004 – SEC-017, SEC-022).

    business accepts order ─▶ collection job OPEN, collection OTP issued
    driver accepts job ─────▶ ASSIGNED
    customer → driver ──────▶ collection OTP     order COLLECTED   job PICKED_UP
    driver → laundry ───────▶ staff scan QR      order RECEIVED    job COMPLETED
    business marks ready ───▶ delivery job OPEN
    laundry → driver ───────▶ driver scans QR    order OUT_FOR_DELIVERY, delivery OTP issued
    driver → customer ──────▶ delivery OTP       order DELIVERED   job COMPLETED
"""

from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import DeliveryJob, HandoverRecord, Incident, Order, User
from app.models.enums import (
    HandoverKind,
    HandoverMethod,
    JobKind,
    JobStatus,
    OrderStatus,
    OtpPurpose,
)
from app.services import audit, notifications, otp, qr, seals
from app.services.order_status import change_status, label
from app.services.search import haversine_km

ACTIVE_JOB = (JobStatus.ASSIGNED, JobStatus.PICKED_UP)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------- Where each job starts and ends ----------

def pickup_point(job: DeliveryJob) -> tuple[float, float]:
    o = job.order
    if job.kind == JobKind.COLLECTION:
        return o.collection_latitude, o.collection_longitude
    return o.business.latitude, o.business.longitude


def dropoff_point(job: DeliveryJob) -> tuple[float, float]:
    o = job.order
    if job.kind == JobKind.COLLECTION:
        return o.business.latitude, o.business.longitude
    return o.delivery_latitude, o.delivery_longitude


def window(job: DeliveryJob) -> tuple[datetime, datetime]:
    o = job.order
    if job.kind == JobKind.COLLECTION:
        return o.collection_window_start, o.collection_window_end
    return o.delivery_window_start, o.delivery_window_end


# ---------- Created by order events ----------

def driver_fee(order: Order, kind: JobKind) -> int:
    # The delivery fee covers both trips; split it, then take the driver's share
    half = order.delivery_fee_cents // 2
    leg = half if kind == JobKind.COLLECTION else order.delivery_fee_cents - half
    return leg * settings.driver_share_percent // 100


def _create(db: Session, order: Order, kind: JobKind) -> DeliveryJob:
    job = DeliveryJob(order=order, kind=kind, status=JobStatus.OPEN,
                      driver_fee_cents=driver_fee(order, kind))
    db.add(job)
    db.flush()
    return job


def on_order_accepted(db: Session, order: Order) -> None:
    _create(db, order, JobKind.COLLECTION)
    otp.issue(db, order, OtpPurpose.COLLECTION)


def on_order_ready(db: Session, order: Order) -> None:
    _create(db, order, JobKind.DELIVERY)


def on_order_cancelled(db: Session, order: Order) -> None:
    for job in order.jobs:
        if job.status in (JobStatus.OPEN, JobStatus.ASSIGNED):
            job.status = JobStatus.CANCELLED
            job.cancelled_at = _now()
    otp.revoke(db, order)


def release_all_for_driver(db: Session, driver: User, reason: str) -> int:
    """When a driver's approval is revoked, jobs not yet picked up go back on
    the board so another driver can take them."""
    jobs = db.scalars(select(DeliveryJob).where(
        DeliveryJob.driver_id == driver.id, DeliveryJob.status == JobStatus.ASSIGNED))
    count = 0
    for job in jobs:
        _unassign(job)
        count += 1
    return count


# ---------- Driver takes / gives back a job ----------

def _unassign(job: DeliveryJob) -> None:
    job.status = JobStatus.OPEN
    job.driver_id = None
    job.assigned_at = None


def accept(db: Session, job: DeliveryJob, driver: User, request: Request) -> None:
    if job.status != JobStatus.OPEN:
        raise _conflict("This job has already been taken")
    if not driver.driver_profile.is_available:
        raise _conflict("Go online before accepting jobs")
    active_count = db.scalar(select(func.count()).select_from(DeliveryJob).where(
        DeliveryJob.driver_id == driver.id, DeliveryJob.status.in_(ACTIVE_JOB)))
    if active_count >= settings.driver_max_active_jobs:
        raise _conflict(f"You already have {active_count} active jobs. "
                        "Finish one before accepting another")
    job.status = JobStatus.ASSIGNED
    job.driver_id = driver.id
    job.assigned_at = _now()
    first = driver.full_name.split()[0]
    what = "collect your laundry" if job.kind == JobKind.COLLECTION else "deliver your laundry"
    notifications.customer(db, job.order, "driver.assigned", "Driver on the way",
                           f"{first} will {what} for order {job.order.order_number}.")
    audit.record(db, "job.accepted", actor_id=driver.id, entity_type="delivery_job",
                 entity_id=job.id,
                 details={"order_number": job.order.order_number, "kind": job.kind.value},
                 request=request)
    db.commit()


def release(db: Session, job: DeliveryJob, driver: User, reason: str, request: Request) -> None:
    """Driver can't do the job after all. Only before picking up the bag."""
    if job.status != JobStatus.ASSIGNED:
        raise _conflict("You can only give back a job before picking up the laundry")
    _unassign(job)
    audit.record(db, "job.released", actor_id=driver.id, entity_type="delivery_job",
                 entity_id=job.id,
                 details={"order_number": job.order.order_number, "reason": reason},
                 request=request)
    db.commit()


# ---------- Handovers ----------

def _record(
    db: Session, job: DeliveryJob, kind: HandoverKind, method: HandoverMethod,
    from_user: User | None, to_user: User | None,
    position: tuple[float, float] | None, expected: tuple[float, float] | None,
) -> HandoverRecord:
    distance_m = None
    flagged = False
    if position and expected:
        distance_m = round(haversine_km(*position, *expected) * 1000, 1)
        flagged = distance_m > settings.handover_location_tolerance_m
    record = HandoverRecord(
        job_id=job.id, kind=kind, method=method,
        from_user_id=from_user.id if from_user else None,
        to_user_id=to_user.id if to_user else None,
        latitude=position[0] if position else None,
        longitude=position[1] if position else None,
        distance_from_expected_m=distance_m, location_flagged=flagged,
    )
    job.order.handovers.append(record)  # keeps order.handovers current in memory
    return record


def _audit_handover(db, actor, job, kind, record, request):
    audit.record(db, f"handover.{kind.value}", actor_id=actor.id, entity_type="order",
                 entity_id=job.order_id,
                 details={"order_number": job.order.order_number, "job_id": str(job.id),
                          "distance_from_expected_m": record.distance_from_expected_m,
                          "location_flagged": record.location_flagged},
                 request=request)


def _require_qr(db: Session, code: str, order: Order, actor: User, request: Request) -> None:
    """The scanned bag must carry this order's current, genuine QR code (SEC-011, SEC-012)."""
    parsed = qr.parse(code)
    problem = None
    if isinstance(parsed, qr.Problem):
        problem, message = parsed.value, "This is not a genuine LaundryConnect order code"
    elif parsed.order_number != order.order_number:
        problem, message = "not_expected_order", "Wrong bag: this code is for a different order"
    elif parsed.version != order.qr_version:
        problem, message = qr.Problem.REPLACED.value, "This label has been replaced"
    if problem:
        audit.record(db, "qr.scan_rejected", actor_id=actor.id, entity_type="order",
                     entity_id=order.id, details={"problem": problem, "code": code[:80]},
                     request=request)
        db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            {"valid": False, "problem": problem, "message": message})


def _expect(job: DeliveryJob, kind: JobKind, job_status: JobStatus,
            order_status: OrderStatus) -> None:
    if job.kind != kind:
        raise _conflict(f"This is a {job.kind.value} job")
    if job.status != job_status:
        raise _conflict(f"This job is {job.status.value.replace('_', ' ')}")
    if job.order.status != order_status:
        raise _conflict(f"The order is {label(job.order.status)}")


def collect(db: Session, job: DeliveryJob, driver: User, code: str,
            position: tuple[float, float], seal_numbers: list[str],
            request: Request) -> HandoverRecord:
    """Customer → driver, verified with the collection OTP (SEC-005, SEC-007, SEC-013).
    The driver records the seals put on the bag(s) (SEC-026)."""
    _expect(job, JobKind.COLLECTION, JobStatus.ASSIGNED, OrderStatus.ACCEPTED)
    order = job.order
    # Seals first: a bad or reused seal must not use up the customer's code
    numbers = seals.ensure_unused(db, order, seal_numbers, driver, request)
    otp.verify(db, order, OtpPurpose.COLLECTION, code, driver, request)
    seals.record(order, JobKind.COLLECTION, numbers, driver)
    job.status = JobStatus.PICKED_UP
    job.picked_up_at = _now()
    change_status(db, order, OrderStatus.COLLECTED, driver)
    notifications.customer(db, order, "order.collected", "Laundry collected",
                           f"Your laundry for order {order.order_number} is on its way to "
                           f"{order.business.business_name}.")
    record = _record(db, job, HandoverKind.CUSTOMER_TO_DRIVER, HandoverMethod.OTP,
                     order.customer, driver, position,
                     (order.collection_latitude, order.collection_longitude))
    _audit_handover(db, driver, job, HandoverKind.CUSTOMER_TO_DRIVER, record, request)
    db.commit()
    return record


def receive(db: Session, order: Order, staff_user: User, code: str, seal_numbers: list[str],
            seals_intact: bool, request: Request) -> tuple[HandoverRecord, Incident | None]:
    """Driver → laundry, verified by staff scanning the bag QR (SEC-011, SEC-014)
    and checking the seals (SEC-027)."""
    job = next((j for j in order.jobs if j.kind == JobKind.COLLECTION), None)
    if job is None or job.status != JobStatus.PICKED_UP or order.status != OrderStatus.COLLECTED:
        raise _conflict(f"This order can't be received now; it is {label(order.status)}")
    _require_qr(db, code, order, staff_user, request)
    incident = seals.check(db, order, JobKind.COLLECTION, seal_numbers, seals_intact,
                           staff_user, request)
    job.status = JobStatus.COMPLETED
    job.completed_at = _now()
    change_status(db, order, OrderStatus.RECEIVED, staff_user)
    notifications.customer(db, order, "order.received", "Laundry arrived",
                           f"{order.business.business_name} has received your laundry for "
                           f"order {order.order_number}.")
    _alert_admins(db, incident)
    record = _record(db, job, HandoverKind.DRIVER_TO_BUSINESS, HandoverMethod.QR,
                     job.driver, staff_user, None, None)
    _audit_handover(db, staff_user, job, HandoverKind.DRIVER_TO_BUSINESS, record, request)
    db.commit()
    return record, incident


def pickup(db: Session, job: DeliveryJob, driver: User, code: str,
           position: tuple[float, float], seal_numbers: list[str],
           request: Request) -> HandoverRecord:
    """Laundry → driver, verified by the driver scanning the bag QR (SEC-011, SEC-015).
    The driver records the laundry's seals on the clean bag(s). Issues the
    delivery OTP to the customer."""
    _expect(job, JobKind.DELIVERY, JobStatus.ASSIGNED, OrderStatus.READY)
    order = job.order
    numbers = seals.ensure_unused(db, order, seal_numbers, driver, request)
    _require_qr(db, code, order, driver, request)
    seals.record(order, JobKind.DELIVERY, numbers, driver)
    job.status = JobStatus.PICKED_UP
    job.picked_up_at = _now()
    change_status(db, order, OrderStatus.OUT_FOR_DELIVERY, driver)
    notifications.customer(db, order, "order.out_for_delivery", "Out for delivery",
                           f"Your clean laundry is on its way. Have your delivery code "
                           f"ready in the app for order {order.order_number}.")
    otp.issue(db, order, OtpPurpose.DELIVERY)
    record = _record(db, job, HandoverKind.BUSINESS_TO_DRIVER, HandoverMethod.QR,
                     None, driver, position, (order.business.latitude, order.business.longitude))
    _audit_handover(db, driver, job, HandoverKind.BUSINESS_TO_DRIVER, record, request)
    db.commit()
    return record


def deliver(db: Session, job: DeliveryJob, driver: User, code: str,
            position: tuple[float, float], seals_intact: bool,
            request: Request) -> tuple[HandoverRecord, Incident | None]:
    """Driver → customer, verified with the delivery OTP (SEC-006, SEC-007, SEC-016).
    The customer confirms the seals are intact; if not, an incident opens."""
    _expect(job, JobKind.DELIVERY, JobStatus.PICKED_UP, OrderStatus.OUT_FOR_DELIVERY)
    order = job.order
    otp.verify(db, order, OtpPurpose.DELIVERY, code, driver, request)
    recorded = [s.seal_number for s in order.seals if s.leg == JobKind.DELIVERY]
    incident = seals.check(db, order, JobKind.DELIVERY, recorded, seals_intact, driver, request)
    job.status = JobStatus.COMPLETED
    job.completed_at = _now()
    change_status(db, order, OrderStatus.DELIVERED, driver)
    notifications.customer(db, order, "order.delivered", "Delivered",
                           f"Order {order.order_number} has been delivered. How did we do? "
                           "Rate your laundry and driver in the app.")
    _alert_admins(db, incident)
    record = _record(db, job, HandoverKind.DRIVER_TO_CUSTOMER, HandoverMethod.OTP,
                     driver, order.customer, position,
                     (order.delivery_latitude, order.delivery_longitude))
    _audit_handover(db, driver, job, HandoverKind.DRIVER_TO_CUSTOMER, record, request)
    db.commit()
    return record, incident


def _alert_admins(db: Session, incident: Incident | None) -> None:
    if incident is not None:
        notifications.notify(db, notifications.admins(db), "incident.high", "Seal check failed",
                             f"{incident.reference}: {incident.description}",
                             order=incident.order, incident=incident)
