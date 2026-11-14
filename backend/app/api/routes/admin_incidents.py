"""Administrators investigate incidents and suspend accounts
(SEC-023, SEC-036, SEC-037, SEC-044, UAT-013). Admin only (SEC-020)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession, require_admin
from app.api.routes.business_orders import business_order_out
from app.api.routes.incidents import summary, update_out
from app.models import EvidencePhoto, Incident, IncidentUpdate, Order, User
from app.models.enums import (
    AccountStatus,
    IncidentCategory,
    IncidentStatus,
    UserRole,
)
from app.schemas.incidents import (
    AdminIncidentOut,
    CommentIn,
    EvidenceOut,
    HandoverDetailOut,
    IncidentPage,
    IncidentSummaryOut,
    PhotoOut,
    SeverityIn,
    StatusIn,
    SuspendIn,
)
from app.schemas.orders import SealOut
from app.services import audit, jobs
from app.services import incidents as incident_service

router = APIRouter(prefix="/api/admin", tags=["admin: incidents"],
                   dependencies=[Depends(require_admin)])


def _evidence(db: DbSession, order: Order) -> EvidenceOut:
    history = business_order_out(order).history
    photos = db.scalars(select(EvidencePhoto).where(EvidencePhoto.order_id == order.id)
                        .order_by(EvidencePhoto.created_at))
    return EvidenceOut(
        order_id=order.id, order_number=order.order_number, order_status=order.status,
        business_name=order.business.business_name, customer_name=order.customer.full_name,
        history=history,
        handovers=[HandoverDetailOut(
            kind=h.kind, method=h.method, created_at=h.created_at,
            from_name=h.from_user.full_name if h.from_user else order.business.business_name,
            to_name=h.to_user.full_name if h.to_user else None,
            latitude=h.latitude, longitude=h.longitude,
            distance_from_expected_m=h.distance_from_expected_m,
            location_flagged=h.location_flagged,
        ) for h in order.handovers],
        seals=[SealOut.model_validate(s) for s in order.seals],
        photos=[PhotoOut.model_validate(p) for p in photos],
    )


def admin_view(db: DbSession, i: Incident) -> AdminIncidentOut:
    incident_photos = db.scalars(select(EvidencePhoto).where(EvidencePhoto.incident_id == i.id)
                                 .order_by(EvidencePhoto.created_at))
    return AdminIncidentOut(
        **summary(i), order_id=i.order_id, description=i.description,
        resolution=i.resolution, closed_at=i.closed_at,
        updates=[update_out(u, staff_view=True) for u in i.updates],
        reporter_id=i.reported_by_id, reporter_name=i.reported_by.full_name,
        reporter_role=i.reporter_role,
        assigned_admin_name=i.assigned_admin.full_name if i.assigned_admin else None,
        evidence=_evidence(db, i.order) if i.order else None,
        incident_photos=[PhotoOut.model_validate(p) for p in incident_photos],
    )


def _get(db: DbSession, incident_id: uuid.UUID, lock: bool = False) -> Incident:
    incident = db.get(Incident, incident_id, with_for_update=lock)
    if incident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Incident not found")
    return incident


# ---------- Incidents ----------

@router.get("/incidents", response_model=IncidentPage)
def list_incidents(
    db: DbSession,
    status_: Annotated[list[IncidentStatus] | None, Query(alias="status")] = None,
    category: IncidentCategory | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IncidentPage:
    """Open and investigating cases by default, oldest first."""
    where = [Incident.status.in_(status_ or [IncidentStatus.OPEN,
                                             IncidentStatus.INVESTIGATING])]
    if category:
        where.append(Incident.category == category)
    total = db.scalar(select(func.count()).select_from(Incident).where(*where))
    rows = db.scalars(select(Incident).where(*where)
                      .order_by(Incident.created_at, Incident.id).limit(limit).offset(offset))
    return IncidentPage(items=[IncidentSummaryOut(**summary(i)) for i in rows],
                        total=total, limit=limit, offset=offset)


@router.get("/incidents/{incident_id}", response_model=AdminIncidentOut)
def get_incident(incident_id: uuid.UUID, db: DbSession, admin: AdminUser,
                 request: Request) -> AdminIncidentOut:
    """The case with all evidence: status history, handovers with GPS, seals, photos."""
    incident = _get(db, incident_id)
    audit.record(db, "incident.viewed", actor_id=admin.id, entity_type="incident",
                 entity_id=incident.id, request=request)
    db.commit()
    return admin_view(db, incident)


@router.post("/incidents/{incident_id}/status", response_model=AdminIncidentOut)
def change_incident_status(incident_id: uuid.UUID, body: StatusIn, db: DbSession,
                           admin: AdminUser, request: Request) -> AdminIncidentOut:
    incident = _get(db, incident_id, lock=True)
    incident_service.change_status(db, incident, admin, body.status, body.note,
                                   body.resolution, request)
    return admin_view(db, incident)


@router.post("/incidents/{incident_id}/comments", response_model=AdminIncidentOut)
def comment_on_incident(incident_id: uuid.UUID, body: CommentIn, db: DbSession,
                        admin: AdminUser, request: Request) -> AdminIncidentOut:
    incident = _get(db, incident_id, lock=True)
    incident_service.comment(db, incident, admin, body.note, body.internal, request)
    return admin_view(db, incident)


@router.patch("/incidents/{incident_id}", response_model=AdminIncidentOut)
def set_severity(incident_id: uuid.UUID, body: SeverityIn, db: DbSession, admin: AdminUser,
                 request: Request) -> AdminIncidentOut:
    incident = _get(db, incident_id, lock=True)
    changes = audit.apply_changes(incident, {"severity": body.severity})
    if changes:
        audit.record(db, "incident.updated", actor_id=admin.id, entity_type="incident",
                     entity_id=incident.id, details=changes, request=request)
        db.commit()
    return admin_view(db, incident)


# ---------- Account suspension (SEC-044) ----------

def _target(db: DbSession, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id, with_for_update=True)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.role == UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Administrator accounts can't be suspended here")
    return user


@router.post("/users/{user_id}/suspend")
def suspend_user(user_id: uuid.UUID, body: SuspendIn, db: DbSession, admin: AdminUser,
                 request: Request) -> dict:
    """Blocks the account immediately – existing logins stop working. A driver
    also goes offline and loses jobs not yet picked up."""
    user = _target(db, user_id)
    if user.status == AccountStatus.SUSPENDED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Account is already suspended")
    incident = _get(db, body.incident_id) if body.incident_id else None

    previous = user.status
    user.status = AccountStatus.SUSPENDED
    released = 0
    if user.driver_profile is not None:
        user.driver_profile.is_available = False
        released = jobs.release_all_for_driver(db, user, body.reason)
    if incident is not None:
        incident.updates.append(IncidentUpdate(
            author_id=admin.id, internal=True,
            note=f"Suspended {user.full_name} ({user.role.value}): {body.reason}"))
    audit.record(db, "user.suspended", actor_id=admin.id, entity_type="user",
                 entity_id=user.id,
                 details={"reason": body.reason, "previous_status": previous.value,
                          "incident": incident.reference if incident else None,
                          "jobs_released": released},
                 request=request)
    db.commit()
    return {"user_id": str(user.id), "status": user.status.value, "jobs_released": released}


@router.post("/users/{user_id}/reinstate")
def reinstate_user(user_id: uuid.UUID, body: SuspendIn, db: DbSession, admin: AdminUser,
                   request: Request) -> dict:
    user = _target(db, user_id)
    if user.status != AccountStatus.SUSPENDED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Account is not suspended")
    user.status = AccountStatus.ACTIVE
    audit.record(db, "user.reinstated", actor_id=admin.id, entity_type="user",
                 entity_id=user.id, details={"reason": body.reason}, request=request)
    db.commit()
    return {"user_id": str(user.id), "status": user.status.value}
