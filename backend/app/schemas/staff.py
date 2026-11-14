import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.enums import BusinessStaffRole
from app.schemas.validators import normalise_sa_phone

# Owners can't be added or assigned through the API – a business has one owner
AssignableRole = Literal[BusinessStaffRole.MANAGER, BusinessStaffRole.ATTENDANT]


class StaffIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    full_name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    phone: Annotated[str, AfterValidator(normalise_sa_phone)] | None = None
    staff_role: AssignableRole

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.lower()


class StaffUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    staff_role: AssignableRole | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def something_to_change(self) -> Self:
        if not self.model_fields_set or any(
            getattr(self, f) is None for f in self.model_fields_set
        ):
            raise ValueError("Send staff_role and/or is_active")
        return self


class StaffOut(BaseModel):
    id: uuid.UUID  # the membership id, used in the URLs below
    user_id: uuid.UUID
    full_name: str
    email: str
    phone: str | None
    staff_role: BusinessStaffRole
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None
    added_by_name: str | None
    created_at: datetime


class TemporaryPasswordOut(BaseModel):
    """Shown once. Give it to the staff member in person; they must change it
    when they first log in."""

    temporary_password: str


class StaffCreatedOut(StaffOut, TemporaryPasswordOut):
    pass
