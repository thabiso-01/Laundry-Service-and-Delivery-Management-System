import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, false
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import AccountStatus, UserRole
from app.models.mixins import TimestampMixin, pg_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.profiles import (
        BusinessProfile,
        BusinessStaff,
        CustomerProfile,
        DriverProfile,
    )
    from app.models.verification import VerificationDocument


class User(TimestampMixin, Base):
    """One login account. Role-specific data lives in the profile tables."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    # Stored lower-cased by the application before saving
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True)  # E.164, e.g. +27821234567
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(150))

    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, "user_role"), index=True)
    status: Mapped[AccountStatus] = mapped_column(
        pg_enum(AccountStatus, "account_status"), default=AccountStatus.ACTIVE
    )

    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set for accounts created with a temporary password (e.g. staff added by an
    # owner); the user must choose their own password before doing anything else.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    # Login tokens issued before this moment are rejected, so changing a
    # password logs out every other session.
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Brute-force protection (SEC-040): repeated wrong passwords lock the account briefly
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Two-step login with an authenticator app (SEC-039). The secret is
    # encrypted; recovery codes are stored only as SHA-256 hashes.
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(String(255))
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_last_step: Mapped[int | None] = mapped_column(BigInteger)  # blocks code replay
    mfa_recovery_hashes: Mapped[list[str] | None] = mapped_column(JSONB)
    # POPIA: record when the user accepted the privacy policy
    privacy_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # POPIA s24: when the user deleted their account (personal details are wiped,
    # the row stays so retained records still point at an anonymous account)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer_profile: Mapped["CustomerProfile | None"] = relationship(back_populates="user")
    driver_profile: Mapped["DriverProfile | None"] = relationship(
        back_populates="user", foreign_keys="DriverProfile.user_id"
    )
    # The business this user owns (legal/accountable owner)
    business_profile: Mapped["BusinessProfile | None"] = relationship(
        back_populates="owner", foreign_keys="BusinessProfile.owner_user_id"
    )
    # The business this user works at (owners, managers and attendants all have one)
    staff_membership: Mapped["BusinessStaff | None"] = relationship(
        back_populates="user", foreign_keys="BusinessStaff.user_id"
    )
    documents: Mapped[list["VerificationDocument"]] = relationship(
        back_populates="user", foreign_keys="VerificationDocument.user_id"
    )
