"""In-app notifications (UR-016, SEC-045).

Every important event writes a message to the user's inbox in the same
transaction as the change it describes. The most important kinds are also
queued for SMS (see app/services/sms.py), sent only after the transaction
commits, to users who have a phone number and haven't switched SMS off.

Messages never contain one-time codes: those are only shown in the app.
"""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BusinessStaff, Incident, Notification, Order, User
from app.models.enums import AccountStatus, BusinessStaffRole, UserRole
from app.services.sms import SMS_KINDS


def notify(
    db: Session,
    users: Iterable[User | None],
    kind: str,
    title: str,
    body: str,
    *,
    order: Order | None = None,
    incident: Incident | None = None,
) -> None:
    seen = set()
    for user in users:
        if user is None or user.id in seen or user.status != AccountStatus.ACTIVE:
            continue
        seen.add(user.id)
        wants_sms = kind in SMS_KINDS and bool(user.phone) and user.sms_enabled
        db.add(Notification(user_id=user.id, kind=kind, title=title, body=body,
                            order_id=order.id if order else None,
                            incident_id=incident.id if incident else None,
                            sms_status="pending" if wants_sms else None))


def business_team(db: Session, business_id) -> list[User]:
    """Owner and managers – the people who run the order queue."""
    return [m.user for m in db.scalars(select(BusinessStaff).where(
        BusinessStaff.business_id == business_id,
        BusinessStaff.is_active.is_(True),
        BusinessStaff.staff_role.in_([BusinessStaffRole.OWNER, BusinessStaffRole.MANAGER]),
    ))]


def admins(db: Session) -> list[User]:
    return list(db.scalars(select(User).where(User.role == UserRole.ADMIN,
                                              User.status == AccountStatus.ACTIVE)))


def customer(db: Session, order: Order, kind: str, title: str, body: str) -> None:
    notify(db, [order.customer], kind, title, body, order=order)
