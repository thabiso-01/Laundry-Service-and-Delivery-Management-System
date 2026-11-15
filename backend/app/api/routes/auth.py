"""Registration, login and 'who am I' (UR-001 – UR-003, SEC-038).

There is deliberately no public endpoint for creating administrators (SEC-020).
Admins are created from the command line: python -m app.scripts.create_admin
"""

import hashlib
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, UserPendingPasswordChange
from app.config import settings
from app.core import mfa
from app.core.ratelimit import rate_limit
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    create_mfa_token,
    decode_mfa_token,
    hash_password,
    verify_password,
)
from app.models import (
    AuditLog,
    BusinessProfile,
    BusinessStaff,
    CustomerProfile,
    DriverProfile,
    User,
)
from app.models.enums import AccountStatus, BusinessStaffRole, UserRole
from app.schemas.auth import (
    BusinessMembershipOut,
    ChangePasswordIn,
    BusinessRegister,
    CustomerRegister,
    DriverRegister,
    DriverStatusOut,
    MeOut,
    MfaCodeIn,
    MfaDisableIn,
    MfaEnabledOut,
    MfaLoginIn,
    MfaSetupOut,
    RegisterBase,
    TokenOut,
    UserOut,
)
from app.services import audit, notifications

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOGIN_FAILED = "Incorrect email or password"


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _new_user(db: DbSession, data: RegisterBase, role: UserRole) -> User:
    """Creates (but doesn't commit) the login account shared by every role."""
    conditions = [User.email == data.email]
    if data.phone:
        conditions.append(User.phone == data.phone)
    clash = db.scalar(select(User).where(or_(*conditions)).limit(1))
    if clash is not None:
        field = "email address" if clash.email == data.email else "phone number"
        raise _conflict(f"An account with this {field} already exists")

    user = User(
        email=data.email,
        phone=data.phone,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role=role,
        status=AccountStatus.ACTIVE,
        privacy_consent_at=datetime.now(UTC),
    )
    db.add(user)
    return user


def _commit(db: DbSession) -> None:
    try:
        db.commit()
    except IntegrityError:
        # Two sign-ups with the same details at the same moment
        db.rollback()
        raise _conflict("An account with these details already exists")


@router.post("/register/customer", response_model=UserOut, status_code=status.HTTP_201_CREATED,
             dependencies=[rate_limit("register", lambda: settings.ratelimit_register_per_hour, 3600)])
def register_customer(data: CustomerRegister, db: DbSession, request: Request) -> User:
    user = _new_user(db, data, UserRole.CUSTOMER)
    address = data.address.model_dump() if data.address else {}
    user.customer_profile = CustomerProfile(**address)
    db.flush()
    audit.record(db, "user.registered", actor_id=user.id, entity_type="user",
                 entity_id=user.id, details={"role": "customer"}, request=request)
    _commit(db)
    return user


@router.post("/register/driver", response_model=UserOut, status_code=status.HTTP_201_CREATED,
             dependencies=[rate_limit("register", lambda: settings.ratelimit_register_per_hour, 3600)])
def register_driver(data: DriverRegister, db: DbSession, request: Request) -> User:
    if db.scalar(select(DriverProfile).where(DriverProfile.id_number == data.id_number)):
        raise _conflict("A driver with this ID number is already registered")

    user = _new_user(db, data, UserRole.DRIVER)
    # Starts as PENDING: the driver can log in and upload documents but cannot
    # take jobs until an admin approves them (SEC-003, SEC-004).
    user.driver_profile = DriverProfile(
        id_number=data.id_number,
        vehicle_type=data.vehicle_type,
        vehicle_registration=data.vehicle_registration,
    )
    db.flush()
    audit.record(db, "user.registered", actor_id=user.id, entity_type="user",
                 entity_id=user.id, details={"role": "driver"}, request=request)
    _commit(db)
    return user


@router.post("/register/business", response_model=UserOut, status_code=status.HTTP_201_CREATED,
             dependencies=[rate_limit("register", lambda: settings.ratelimit_register_per_hour, 3600)])
def register_business(data: BusinessRegister, db: DbSession, request: Request) -> User:
    if data.registration_number and db.scalar(
        select(BusinessProfile).where(
            BusinessProfile.registration_number == data.registration_number
        )
    ):
        raise _conflict("A business with this registration number is already registered")

    user = _new_user(db, data, UserRole.BUSINESS)
    # Starts as PENDING: can't receive orders until verified (SEC-043).
    business = BusinessProfile(
        owner=user,
        business_name=data.business_name,
        registration_number=data.registration_number,
        description=data.description,
        contact_phone=data.contact_phone,
        contact_email=data.contact_email,
        **data.address.model_dump(),
    )
    business.staff.append(BusinessStaff(user=user, staff_role=BusinessStaffRole.OWNER))
    db.add(business)
    db.flush()
    audit.record(db, "user.registered", actor_id=user.id, entity_type="user",
                 entity_id=user.id, details={"role": "business"}, request=request)
    audit.record(db, "business.registered", actor_id=user.id, entity_type="business_profile",
                 entity_id=business.id, details={"name": business.business_name},
                 request=request)
    _commit(db)
    return user


def _locked_response(db: DbSession, user: User, request: Request) -> HTTPException | None:
    now = datetime.now(UTC)
    if user.locked_until and user.locked_until > now:
        minutes = math.ceil((user.locked_until - now).total_seconds() / 60)
        audit.record(db, "auth.login_while_locked", actor_id=user.id, request=request)
        db.commit()
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                             f"Too many failed attempts. Try again in {minutes} minute(s)")
    return None


def _register_failure(db: DbSession, user: User, reason: str, request: Request) -> None:
    """Counts a wrong password or MFA code; too many locks the account (SEC-040)."""
    user.failed_login_count += 1
    audit.record(db, "auth.login_failed", actor_id=user.id,
                 details={"reason": reason, "count": user.failed_login_count}, request=request)
    if user.failed_login_count >= settings.login_max_failures:
        user.failed_login_count = 0
        user.locked_until = datetime.now(UTC) + timedelta(minutes=settings.login_lockout_minutes)
        audit.record(db, "auth.locked", actor_id=user.id,
                     details={"minutes": settings.login_lockout_minutes}, request=request)
        notifications.notify(
            db, [user], "security.locked", "Sign-in locked",
            f"Someone entered the wrong password for your account {settings.login_max_failures} "
            f"times. Sign-in is paused for {settings.login_lockout_minutes} minutes. If this "
            "wasn't you, change your password.")
    db.commit()


def _device(request: Request) -> str:
    """A coarse fingerprint of where a login came from (IP + browser)."""
    ip = request.client.host if request.client else ""
    agent = request.headers.get("user-agent", "")
    return hashlib.sha256(f"{ip}|{agent}".encode()).hexdigest()[:16]


def _complete_login(db: DbSession, user: User, request: Request) -> TokenOut:
    device = _device(request)
    seen_before = db.scalar(select(AuditLog.id).where(
        AuditLog.actor_user_id == user.id, AuditLog.action == "auth.login").limit(1))
    known_device = db.scalar(select(AuditLog.id).where(
        AuditLog.actor_user_id == user.id, AuditLog.action == "auth.login",
        AuditLog.details["device"].astext == device).limit(1))
    if seen_before and not known_device:
        # SEC-045: tell the user about sign-ins from somewhere new
        agent = (request.headers.get("user-agent") or "an unknown browser")[:80]
        notifications.notify(
            db, [user], "security.new_device", "New sign-in to your account",
            f"Your account was signed in to from a new device ({agent}). If this wasn't "
            "you, change your password now and contact support.")
        audit.record(db, "auth.new_device", actor_id=user.id, details={"device": device},
                     request=request)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(UTC)
    audit.record(db, "auth.login", actor_id=user.id, details={"device": device}, request=request)
    db.commit()
    token, expires_in = create_access_token(user.id, user.role.value)
    return TokenOut(access_token=token, expires_in=expires_in,
                    must_change_password=user.must_change_password)


@router.post("/login", response_model=TokenOut,
             dependencies=[rate_limit("login-minute", lambda: settings.ratelimit_login_per_minute, 60), rate_limit("login-hour", lambda: settings.ratelimit_login_per_hour, 3600)])
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
    request: Request,
) -> TokenOut:
    """Log in with email (sent in the `username` field) and password.

    Uses the standard OAuth2 form so the Authorize button on /docs works.
    With two-step login on, this returns `mfa_required` and an `mfa_token`
    instead of an access token: send it with the app code to /login/mfa.
    """
    email = form.username.strip().lower()
    user = db.scalar(select(User).where(User.email == email).with_for_update())

    if user is None:
        verify_password(form.password, DUMMY_HASH)  # same timing as a real check
        audit.record(db, "auth.login_failed", details={"email": email, "reason": "unknown_email"},
                     request=request)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, LOGIN_FAILED,
                            headers={"WWW-Authenticate": "Bearer"})

    if locked := _locked_response(db, user, request):
        raise locked

    valid, new_hash = verify_password(form.password, user.password_hash)
    if not valid:
        _register_failure(db, user, "wrong_password", request)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, LOGIN_FAILED,
                            headers={"WWW-Authenticate": "Bearer"})

    if user.status != AccountStatus.ACTIVE:
        audit.record(db, "auth.login_blocked", actor_id=user.id,
                     details={"status": user.status.value}, request=request)
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Account is {user.status.value}")

    if new_hash:
        user.password_hash = new_hash
    if user.mfa_enabled_at:
        token, expires_in = create_mfa_token(user.id)
        audit.record(db, "auth.mfa_challenge", actor_id=user.id, request=request)
        db.commit()
        return TokenOut(access_token=None, expires_in=expires_in, mfa_required=True,
                        mfa_token=token)
    return _complete_login(db, user, request)


def _check_second_factor(user: User, code: str) -> bool:
    """A current authenticator code, or an unused recovery code (used up)."""
    secret = mfa.decrypt(user.mfa_secret_encrypted or "")
    if secret:
        step = mfa.verify(secret, code, user.mfa_last_step)
        if step is not None:
            user.mfa_last_step = step
            return True
    hashed = mfa.hash_recovery(code)
    remaining = list(user.mfa_recovery_hashes or [])
    if hashed in remaining:
        remaining.remove(hashed)
        user.mfa_recovery_hashes = remaining  # each recovery code works once
        return True
    return False


@router.post("/login/mfa", response_model=TokenOut,
             dependencies=[rate_limit("login-minute", lambda: settings.ratelimit_login_per_minute, 60), rate_limit("login-hour", lambda: settings.ratelimit_login_per_hour, 3600)])
def login_mfa(body: MfaLoginIn, db: DbSession, request: Request) -> TokenOut:
    """Second step of login: the 6-digit code from the authenticator app, or a
    recovery code."""
    claims = decode_mfa_token(body.mfa_token)
    user = db.get(User, uuid.UUID(claims["sub"]), with_for_update=True) if claims else None
    if user is None or not user.mfa_enabled_at:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign-in expired; start again")
    if locked := _locked_response(db, user, request):
        raise locked
    if user.status != AccountStatus.ACTIVE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Account is {user.status.value}")
    if not _check_second_factor(user, body.code):
        _register_failure(db, user, "wrong_mfa_code", request)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect code")
    return _complete_login(db, user, request)


# ---------- Two-step login set-up (SEC-039) ----------

@router.post("/mfa/setup", response_model=MfaSetupOut)
def mfa_setup(user: CurrentUser, db: DbSession, request: Request) -> MfaSetupOut:
    """Start turning on two-step login: add this secret to your authenticator
    app (scan otpauth_uri as a QR code), then confirm with /mfa/enable."""
    if user.mfa_enabled_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-step login is already on")
    secret = mfa.new_secret()
    user.mfa_secret_encrypted = mfa.encrypt(secret)
    audit.record(db, "auth.mfa_setup_started", actor_id=user.id, request=request)
    db.commit()
    return MfaSetupOut(secret=secret, otpauth_uri=mfa.provisioning_uri(secret, user.email))


@router.post("/mfa/enable", response_model=MfaEnabledOut)
def mfa_enable(body: MfaCodeIn, user: CurrentUser, db: DbSession,
               request: Request) -> MfaEnabledOut:
    """Confirm with a code from the app. Returns one-time recovery codes –
    store them somewhere safe; they're shown only once."""
    if user.mfa_enabled_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-step login is already on")
    secret = mfa.decrypt(user.mfa_secret_encrypted or "")
    if not secret:
        raise HTTPException(status.HTTP_409_CONFLICT, "Start with /mfa/setup")
    step = mfa.verify(secret, body.code, None)
    if step is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Incorrect code. Check your phone's clock")
    codes = mfa.new_recovery_codes()
    user.mfa_enabled_at = datetime.now(UTC)
    user.mfa_last_step = step
    user.mfa_recovery_hashes = [mfa.hash_recovery(c) for c in codes]
    audit.record(db, "auth.mfa_enabled", actor_id=user.id, request=request)
    notifications.notify(db, [user], "security.mfa_enabled", "Two-step login is on",
                         "Signing in now also needs a code from your authenticator app.")
    db.commit()
    return MfaEnabledOut(recovery_codes=codes)


@router.post("/mfa/disable")
def mfa_disable(body: MfaDisableIn, user: CurrentUser, db: DbSession, request: Request) -> dict:
    if not user.mfa_enabled_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "Two-step login is not on")
    valid, _ = verify_password(body.password, user.password_hash)
    if not valid or not _check_second_factor(user, body.code):
        audit.record(db, "auth.mfa_disable_failed", actor_id=user.id, request=request)
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password or code is incorrect")
    user.mfa_enabled_at = None
    user.mfa_secret_encrypted = None
    user.mfa_last_step = None
    user.mfa_recovery_hashes = None
    audit.record(db, "auth.mfa_disabled", actor_id=user.id, request=request)
    notifications.notify(db, [user], "security.mfa_disabled", "Two-step login turned off",
                         "If this wasn't you, change your password and contact support.")
    db.commit()
    return {"mfa_enabled": False}


@router.post("/change-password", response_model=TokenOut,
             dependencies=[rate_limit("password-change", lambda: settings.ratelimit_password_change_per_15_min, 900)])
def change_password(
    body: ChangePasswordIn, user: UserPendingPasswordChange, db: DbSession, request: Request
) -> TokenOut:
    """Change your password. Every other logged-in session is ended; use the
    token returned here from now on."""
    valid, _ = verify_password(body.current_password, user.password_hash)
    if not valid:
        audit.record(db, "auth.password_change_failed", actor_id=user.id, request=request)
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "New password must be different from the current one")
    if user.privacy_consent_at is None:
        if not body.accept_privacy_policy:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "You must accept the privacy policy to continue")
        user.privacy_consent_at = datetime.now(UTC)

    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    user.password_changed_at = datetime.now(UTC)
    audit.record(db, "auth.password_changed", actor_id=user.id, request=request)
    db.commit()

    token, expires_in = create_access_token(user.id, user.role.value)
    return TokenOut(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=MeOut)
def me(user: UserPendingPasswordChange) -> MeOut:
    out = MeOut.model_validate(user, from_attributes=True)
    out.mfa_enabled = user.mfa_enabled_at is not None
    if user.driver_profile:
        out.driver = DriverStatusOut(
            verification_status=user.driver_profile.verification_status,
            rejection_reason=user.driver_profile.rejection_reason,
            is_available=user.driver_profile.is_available,
        )
    if user.staff_membership:
        m = user.staff_membership
        out.business = BusinessMembershipOut(
            business_id=m.business_id,
            business_name=m.business.business_name,
            business_verification_status=m.business.verification_status,
            business_rejection_reason=m.business.rejection_reason,
            staff_role=m.staff_role,
            is_active=m.is_active,
        )
    return out
