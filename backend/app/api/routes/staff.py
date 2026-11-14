"""Owners and managers manage the people who work at their business
(SEC-011, SEC-017, Business Rule 8).

Who may manage whom:
    owner   → managers and attendants
    manager → attendants only
Nobody can add an owner, change the owner, or change their own access.

There is no email service yet, so a new staff member gets a temporary
password (returned once) to be handed over in person. They must replace it,
and accept the privacy policy themselves, on first login.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, require_business_staff
from app.core.security import generate_temporary_password, hash_password
from app.models import BusinessStaff, User
from app.models.enums import AccountStatus, BusinessStaffRole, UserRole
from app.schemas.staff import (
    StaffCreatedOut,
    StaffIn,
    StaffOut,
    StaffUpdate,
    TemporaryPasswordOut,
)
from app.services import audit

router = APIRouter(prefix="/api/business/staff", tags=["business staff"])

Manager = Annotated[
    BusinessStaff,
    Depends(require_business_staff(BusinessStaffRole.MANAGER, business_must_be_verified=False)),
]


def _out(m: BusinessStaff) -> StaffOut:
    return StaffOut(
        id=m.id,
        user_id=m.user_id,
        full_name=m.user.full_name,
        email=m.user.email,
        phone=m.user.phone,
        staff_role=m.staff_role,
        is_active=m.is_active,
        must_change_password=m.user.must_change_password,
        last_login_at=m.user.last_login_at,
        added_by_name=m.added_by.full_name if m.added_by else None,
        created_at=m.created_at,
    )


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail)


def _check_can_assign(actor: BusinessStaff, role: BusinessStaffRole) -> None:
    if actor.staff_role == BusinessStaffRole.MANAGER and role != BusinessStaffRole.ATTENDANT:
        raise _forbidden("Managers can only manage attendants")


def _target(db: DbSession, actor: BusinessStaff, membership_id: uuid.UUID) -> BusinessStaff:
    target = db.get(BusinessStaff, membership_id, with_for_update=True)
    # Other businesses' staff look like they don't exist
    if target is None or target.business_id != actor.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Staff member not found")
    if target.staff_role == BusinessStaffRole.OWNER:
        raise _forbidden("The owner's access can't be changed here")
    if target.user_id == actor.user_id:
        raise _forbidden("You can't change your own access")
    _check_can_assign(actor, target.staff_role)
    return target


@router.get("", response_model=list[StaffOut])
def list_staff(actor: Manager, db: DbSession) -> list[StaffOut]:
    rank = {BusinessStaffRole.OWNER: 0, BusinessStaffRole.MANAGER: 1,
            BusinessStaffRole.ATTENDANT: 2}
    members = db.scalars(
        select(BusinessStaff).where(BusinessStaff.business_id == actor.business_id)
    ).all()
    members = sorted(members, key=lambda m: (not m.is_active, rank[m.staff_role],
                                             m.user.full_name.lower()))
    return [_out(m) for m in members]


@router.post("", response_model=StaffCreatedOut, status_code=status.HTTP_201_CREATED)
def add_staff(body: StaffIn, actor: Manager, db: DbSession, request: Request) -> StaffCreatedOut:
    _check_can_assign(actor, body.staff_role)

    conditions = [User.email == body.email]
    if body.phone:
        conditions.append(User.phone == body.phone)
    if db.scalar(select(User.id).where(or_(*conditions)).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "An account with this email or phone number already exists")

    temporary = generate_temporary_password()
    user = User(
        email=body.email,
        phone=body.phone,
        full_name=body.full_name,
        password_hash=hash_password(temporary),
        role=UserRole.BUSINESS,
        status=AccountStatus.ACTIVE,
        must_change_password=True,
        privacy_consent_at=None,  # they accept it themselves on first login
    )
    membership = BusinessStaff(business_id=actor.business_id, user=user,
                               staff_role=body.staff_role, added_by_id=actor.user_id)
    db.add(membership)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "An account with this email or phone number already exists")
    audit.record(db, "staff.added", actor_id=actor.user_id, entity_type="business_staff",
                 entity_id=membership.id,
                 details={"user_id": str(user.id), "staff_role": body.staff_role.value},
                 request=request)
    db.commit()
    return StaffCreatedOut(**_out(membership).model_dump(), temporary_password=temporary)


@router.patch("/{membership_id}", response_model=StaffOut)
def update_staff(
    membership_id: uuid.UUID, body: StaffUpdate, actor: Manager, db: DbSession, request: Request
) -> StaffOut:
    """Change someone's role, or deactivate / reactivate them."""
    target = _target(db, actor, membership_id)
    if body.staff_role is not None:
        _check_can_assign(actor, body.staff_role)

    changes = audit.apply_changes(target, body.model_dump(exclude_unset=True))
    if "is_active" in changes:
        # Staff accounts exist only for this job, so leaving the business also
        # blocks the login. Never undo an admin suspension, though.
        user = target.user
        if not target.is_active and user.status == AccountStatus.ACTIVE:
            user.status = AccountStatus.DEACTIVATED
        elif target.is_active and user.status == AccountStatus.DEACTIVATED:
            user.status = AccountStatus.ACTIVE

    if changes:
        audit.record(db, "staff.updated", actor_id=actor.user_id, entity_type="business_staff",
                     entity_id=target.id, details=changes, request=request)
        db.commit()
    return _out(target)


@router.post("/{membership_id}/reset-password", response_model=TemporaryPasswordOut)
def reset_staff_password(
    membership_id: uuid.UUID, actor: Manager, db: DbSession, request: Request
) -> TemporaryPasswordOut:
    """For staff who forgot their password. Logs them out everywhere and
    issues a new temporary password (shown once)."""
    target = _target(db, actor, membership_id)
    temporary = generate_temporary_password()
    user = target.user
    user.password_hash = hash_password(temporary)
    user.must_change_password = True
    user.password_changed_at = datetime.now(UTC)
    audit.record(db, "staff.password_reset", actor_id=actor.user_id,
                 entity_type="business_staff", entity_id=target.id, request=request)
    db.commit()
    return TemporaryPasswordOut(temporary_password=temporary)
