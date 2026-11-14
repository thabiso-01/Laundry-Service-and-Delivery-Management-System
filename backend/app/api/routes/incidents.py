"""Report problems and follow up on your reports (UR-015, SEC-033, SEC-034, SEC-048, UAT-012).

Any logged-in customer, driver or business staff member can report. A report
about an order is only accepted from someone involved in that order.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.models import Incident, IncidentUpdate, Order, User
from app.models.enums import UserRole
from app.schemas.incidents import (
    CommentIn,
    IncidentIn,
    IncidentOut,
    IncidentPage,
    IncidentSummaryOut,
    UpdateOut,
)
from app.services import incidents as incident_service

router = APIRouter(prefix="/api/incidents", tags=["incidents"])

SUPPORT = "LaundryConnect support"


def summary(i: Incident) -> dict:
    return dict(id=i.id, reference=i.reference,
                order_number=i.order.order_number if i.order else None,
                category=i.category, status=i.status, severity=i.severity,
                is_automatic=i.is_automatic, created_at=i.created_at)


def update_out(u: IncidentUpdate, *, staff_view: bool) -> UpdateOut:
    if u.author is None:
        author = "System"
    elif u.author.role == UserRole.ADMIN and not staff_view:
        author = SUPPORT  # admins' names aren't shown to the public
    else:
        author = f"{u.author.full_name} ({u.author.role.value})"
    return UpdateOut(from_status=u.from_status, to_status=u.to_status, note=u.note,
                     internal=u.internal, author=author, created_at=u.created_at)


def reporter_view(i: Incident) -> IncidentOut:
    return IncidentOut(
        **summary(i), order_id=i.order_id, description=i.description,
        resolution=i.resolution, closed_at=i.closed_at,
        # SEC-037 trail, minus admins' internal notes
        updates=[update_out(u, staff_view=False) for u in i.updates if not u.internal],
    )


def _mine(db: DbSession, user: User, incident_id: uuid.UUID, lock: bool = False) -> Incident:
    incident = db.get(Incident, incident_id, with_for_update=lock)
    if incident is None or incident.reported_by_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    return incident


def _not_admin(user: User) -> None:
    if user.role == UserRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Administrators manage reports under /api/admin/incidents")


@router.post("", response_model=IncidentOut, status_code=status.HTTP_201_CREATED)
def report_incident(body: IncidentIn, user: CurrentUser, db: DbSession,
                    request: Request) -> IncidentOut:
    """Report missing, damaged or wrong items, a broken seal, a security
    problem or suspected fraud. You get a reference number to quote (SEC-035)."""
    _not_admin(user)
    order = db.get(Order, body.order_id) if body.order_id else None
    if body.order_id and order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
    incident = incident_service.report(db, user, body.category, body.description, order, request)
    return reporter_view(incident)


@router.get("", response_model=IncidentPage)
def my_reports(
    user: CurrentUser, db: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IncidentPage:
    where = Incident.reported_by_id == user.id
    total = db.scalar(select(func.count()).select_from(Incident).where(where))
    rows = db.scalars(select(Incident).where(where)
                      .order_by(Incident.created_at.desc()).limit(limit).offset(offset))
    return IncidentPage(items=[IncidentSummaryOut(**summary(i)) for i in rows],
                        total=total, limit=limit, offset=offset)


@router.get("/{incident_id}", response_model=IncidentOut)
def get_report(incident_id: uuid.UUID, user: CurrentUser, db: DbSession) -> IncidentOut:
    return reporter_view(_mine(db, user, incident_id))


@router.post("/{incident_id}/comments", response_model=IncidentOut)
def add_information(incident_id: uuid.UUID, body: CommentIn, user: CurrentUser, db: DbSession,
                    request: Request) -> IncidentOut:
    """Add more information to your report while it's open."""
    _not_admin(user)
    incident = _mine(db, user, incident_id, lock=True)
    incident_service.comment(db, incident, user, body.note, False, request)
    return reporter_view(incident)
