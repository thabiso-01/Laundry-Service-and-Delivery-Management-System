"""Incident reports and their investigation (SEC-033 – SEC-037, SEC-048, UR-015, UAT-012/013).

    open ──▶ investigating ──▶ resolved
      │            │      └──▶ dismissed
      └────────────┴─────────▶ dismissed
    resolved / dismissed ──▶ investigating   (reopen)
"""

import secrets
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BusinessStaff, Incident, IncidentUpdate, Order, User
from app.models.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentStatus,
    UserRole,
)
from app.services import audit, notifications

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32
CLOSED = {IncidentStatus.RESOLVED, IncidentStatus.DISMISSED}
TRANSITIONS = {
    IncidentStatus.OPEN: {IncidentStatus.INVESTIGATING, IncidentStatus.DISMISSED},
    IncidentStatus.INVESTIGATING: {IncidentStatus.RESOLVED, IncidentStatus.DISMISSED},
    IncidentStatus.RESOLVED: {IncidentStatus.INVESTIGATING},
    IncidentStatus.DISMISSED: {IncidentStatus.INVESTIGATING},
}
# Reports not tied to an order must be about fraud, security or something general
NO_ORDER_CATEGORIES = {IncidentCategory.FRAUD, IncidentCategory.SECURITY,
                       IncidentCategory.CONDUCT, IncidentCategory.OTHER}


def _reference(db: Session) -> str:
    while True:
        ref = "INC-" + "".join(secrets.choice(_ALPHABET) for _ in range(8))
        if not db.scalar(select(Incident.id).where(Incident.reference == ref)):
            return ref


def is_party(user: User, order: Order) -> bool:
    """Is this user directly involved in the order? (Business Rules 7 – 9)"""
    if user.role == UserRole.CUSTOMER:
        return order.customer_id == user.id
    if user.role == UserRole.BUSINESS:
        m: BusinessStaff | None = user.staff_membership
        return bool(m and m.is_active and m.business_id == order.business_id)
    if user.role == UserRole.DRIVER:
        return any(j.driver_id == user.id for j in order.jobs)
    return False


def open_incident(
    db: Session,
    *,
    reporter: User,
    category: IncidentCategory,
    description: str,
    order: Order | None,
    request: Request | None,
    automatic: bool = False,
    severity: IncidentSeverity = IncidentSeverity.MEDIUM,
) -> Incident:
    """Creates the incident (caller commits)."""
    incident = Incident(
        reference=_reference(db),
        order_id=order.id if order else None,
        reported_by_id=reporter.id,
        reporter_role=reporter.role,
        is_automatic=automatic,
        category=category,
        description=description,
        status=IncidentStatus.OPEN,
        severity=severity,
    )
    incident.updates.append(IncidentUpdate(
        author_id=reporter.id, to_status=IncidentStatus.OPEN,
        note="Opened automatically by the system" if automatic else "Reported",
    ))
    db.add(incident)
    db.flush()
    audit.record(db, "incident.opened", actor_id=reporter.id, entity_type="incident",
                 entity_id=incident.id,
                 details={"reference": incident.reference, "category": category.value,
                          "automatic": automatic,
                          "order_number": order.order_number if order else None},
                 request=request)
    return incident


def report(
    db: Session, reporter: User, category: IncidentCategory, description: str,
    order: Order | None, request: Request,
) -> Incident:
    if order is not None and not is_party(reporter, order):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    if order is None and category not in NO_ORDER_CATEGORIES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Choose the order this report is about")
    incident = open_incident(db, reporter=reporter, category=category,
                             description=description, order=order, request=request)
    db.commit()
    return incident


def comment(db: Session, incident: Incident, author: User, note: str, internal: bool,
            request: Request) -> None:
    if author.role != UserRole.ADMIN:
        internal = False
        if incident.status in CLOSED:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "This case is closed. Open a new report if needed")
    incident.updates.append(IncidentUpdate(author_id=author.id, note=note, internal=internal))
    if author.role == UserRole.ADMIN and not internal:
        notifications.notify(db, [incident.reported_by], "incident.update",
                             f"Update on {incident.reference}", note, incident=incident)
    audit.record(db, "incident.commented", actor_id=author.id, entity_type="incident",
                 entity_id=incident.id,
                 details={"reference": incident.reference, "internal": internal},
                 request=request)
    db.commit()


def change_status(
    db: Session, incident: Incident, admin: User, to: IncidentStatus, note: str | None,
    resolution: str | None, request: Request,
) -> None:
    if to not in TRANSITIONS[incident.status]:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"A case that is {incident.status.value} can't become {to.value}")
    if to in CLOSED and not resolution:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Write down the outcome before closing the case")
    previous = incident.status
    incident.status = to
    if incident.assigned_admin_id is None:
        incident.assigned_admin = admin  # set the object, so the relationship is never stale
    if to in CLOSED:
        incident.resolution = resolution
        incident.closed_at = datetime.now(UTC)
    else:
        incident.closed_at = None
    incident.updates.append(IncidentUpdate(
        author_id=admin.id, from_status=previous, to_status=to,
        note=resolution if to in CLOSED else note,
    ))
    notifications.notify(
        db, [incident.reported_by], "incident.status", f"{incident.reference} is now {to.value}",
        resolution if to in CLOSED and resolution else (note or f"Your report is {to.value}."),
        incident=incident)
    audit.record(db, "incident.status_changed", actor_id=admin.id, entity_type="incident",
                 entity_id=incident.id,
                 details={"reference": incident.reference, "from": previous.value,
                          "to": to.value},
                 request=request)
    db.commit()
