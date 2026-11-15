import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import (
    AccountStatus,
    BusinessStaffRole,
    UserRole,
    VehicleType,
    VerificationStatus,
)
from app.schemas.validators import normalise_id_number, normalise_sa_phone

SAPhone = Annotated[str, AfterValidator(normalise_sa_phone)]
Password = Annotated[str, Field(min_length=10, max_length=128)]
Name = Annotated[str, Field(min_length=2, max_length=150)]


# ---------- Registration input ----------

class AddressIn(BaseModel):
    address_line: str | None = Field(default=None, max_length=255)
    suburb: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=100)
    province: str | None = Field(default=None, max_length=50)
    postal_code: str | None = Field(default=None, max_length=10)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class RegisterBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: EmailStr
    password: Password
    full_name: Name
    phone: SAPhone | None = None
    # NFR-009 / POPIA: users must actively agree before we store their data
    accept_privacy_policy: bool

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("accept_privacy_policy")
    @classmethod
    def must_accept(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must accept the privacy policy to register")
        return v


class CustomerRegister(RegisterBase):
    address: AddressIn | None = None


class DriverRegister(RegisterBase):
    id_number: Annotated[str, AfterValidator(normalise_id_number)]
    vehicle_type: VehicleType | None = None
    vehicle_registration: str | None = Field(default=None, max_length=20)


class BusinessRegister(RegisterBase):
    """Registers the owner's login account and the business together."""

    business_name: Name
    registration_number: str | None = Field(default=None, max_length=30)  # CIPC
    description: str | None = Field(default=None, max_length=2000)
    contact_phone: SAPhone | None = None
    contact_email: EmailStr | None = None
    address: AddressIn


# ---------- Output ----------

class TokenOut(BaseModel):
    # Missing when a second step (MFA) is still needed – see mfa_token
    access_token: str | None
    token_type: str = "bearer"
    expires_in: int  # seconds (of the access token, or of the mfa_token)
    # When true the frontend should go straight to the change-password screen
    must_change_password: bool = False
    # Two-step login: send mfa_token plus the app code to /api/auth/login/mfa
    mfa_required: bool = False
    mfa_token: str | None = None


class MfaLoginIn(BaseModel):
    mfa_token: str = Field(max_length=2000)
    code: str = Field(min_length=6, max_length=20, description="App code or recovery code")


class MfaCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class MfaDisableIn(BaseModel):
    password: str = Field(max_length=128)
    code: str = Field(min_length=6, max_length=20)


class MfaSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class MfaEnabledOut(BaseModel):
    recovery_codes: list[str]


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: Password
    # Required for accounts someone else created (e.g. staff), who haven't
    # agreed to the privacy policy themselves yet (POPIA)
    accept_privacy_policy: bool | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    role: UserRole
    status: AccountStatus
    must_change_password: bool
    created_at: datetime


class DriverStatusOut(BaseModel):
    verification_status: VerificationStatus
    rejection_reason: str | None = None
    is_available: bool


class BusinessMembershipOut(BaseModel):
    business_id: uuid.UUID
    business_name: str
    business_verification_status: VerificationStatus
    business_rejection_reason: str | None = None
    staff_role: BusinessStaffRole
    is_active: bool


class MeOut(UserOut):
    """The logged-in user plus what the frontend needs to show the right screens."""

    driver: DriverStatusOut | None = None
    business: BusinessMembershipOut | None = None
    mfa_enabled: bool = False
    sms_enabled: bool = True
