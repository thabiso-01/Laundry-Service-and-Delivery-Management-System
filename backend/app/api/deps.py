"""Role-based access control (SEC-018 – SEC-020).

Use these as FastAPI dependencies on every protected route, e.g.

    @router.get("/admin/users", dependencies=[Depends(require_admin)])
    def list_users(...): ...

    @router.post("/jobs/{id}/accept")
    def accept_job(driver: ApprovedDriver): ...

    @router.patch("/orders/{id}/status")
    def update_status(staff: Annotated[BusinessStaff, Depends(require_business_staff())]): ...

Permissions are always read from the database on each request, never trusted
from the token, so suspending a user or revoking approval takes effect at once.
"""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database import get_db
from app.models import BusinessStaff, DriverProfile, User
from app.models.enums import AccountStatus, BusinessStaffRole, UserRole, VerificationStatus

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

DbSession = Annotated[Session, Depends(get_db)]


def _unauthorised(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


PASSWORD_CHANGE_REQUIRED = "You must change your temporary password before continuing"


def get_user_pending_password_change(
    token: Annotated[str, Depends(oauth2_scheme)], db: DbSession
) -> User:
    """Authenticates the token but still allows users who must change their
    password. Only for /me and the change-password route."""
    claims = decode_access_token(token)
    if claims is None:
        raise _unauthorised("Invalid or expired token")
    try:
        user_id = uuid.UUID(claims["sub"])
    except ValueError:
        raise _unauthorised("Invalid or expired token")

    user = db.get(User, user_id)
    if user is None:
        raise _unauthorised("Invalid or expired token")
    # Tokens issued before the last password change are dead (iat is whole seconds)
    if user.password_changed_at and claims["iat"] < int(user.password_changed_at.timestamp()):
        raise _unauthorised("Session ended because the password was changed")
    if user.status != AccountStatus.ACTIVE:
        raise _forbidden(f"Account is {user.status.value}")
    return user


def get_current_user(
    user: Annotated[User, Depends(get_user_pending_password_change)],
) -> User:
    if user.must_change_password:
        raise _forbidden(PASSWORD_CHANGE_REQUIRED)
    return user


UserPendingPasswordChange = Annotated[User, Depends(get_user_pending_password_change)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[..., User]:
    """Allow only users whose platform role is one of `roles` (SEC-019)."""

    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise _forbidden("You do not have permission to do this")
        return user

    return checker


require_admin = require_roles(UserRole.ADMIN)  # SEC-020
require_customer = require_roles(UserRole.CUSTOMER)
AdminUser = Annotated[User, Depends(require_admin)]
CustomerUser = Annotated[User, Depends(require_customer)]


def require_approved_driver(
    user: Annotated[User, Depends(require_roles(UserRole.DRIVER))],
) -> DriverProfile:
    """SEC-004 / Business Rule 3: only admin-approved drivers may take jobs."""
    profile = user.driver_profile
    if profile is None or profile.verification_status != VerificationStatus.APPROVED:
        raise _forbidden("Your driver account is awaiting approval")
    return profile


ApprovedDriver = Annotated[DriverProfile, Depends(require_approved_driver)]

_STAFF_RANK = {
    BusinessStaffRole.ATTENDANT: 1,
    BusinessStaffRole.MANAGER: 2,
    BusinessStaffRole.OWNER: 3,
}


def require_business_staff(
    min_role: BusinessStaffRole = BusinessStaffRole.ATTENDANT,
    *,
    business_must_be_verified: bool = True,
) -> Callable[..., BusinessStaff]:
    """Allow active staff of a business at `min_role` or higher.

    By default the business must also be admin-verified (SEC-043 / Business
    Rule 2). Pass business_must_be_verified=False for things a pending
    business still needs, such as uploading verification documents.

    Returns the membership, so the route knows which business to scope
    queries to (Business Rule 8: only your own business's orders).
    """

    def checker(user: Annotated[User, Depends(require_roles(UserRole.BUSINESS))]) -> BusinessStaff:
        membership = user.staff_membership
        if membership is None or not membership.is_active:
            raise _forbidden("You are not an active member of a laundry business")
        if _STAFF_RANK[membership.staff_role] < _STAFF_RANK[min_role]:
            raise _forbidden(f"This requires the {min_role.value} role or higher")
        if (
            business_must_be_verified
            and membership.business.verification_status != VerificationStatus.APPROVED
        ):
            raise _forbidden("Your business is awaiting verification")
        return membership

    return checker
