import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import BusinessStaffRole, VehicleType, VerificationStatus
from app.models.mixins import TimestampMixin, pg_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.catalog import LaundryService
    from app.models.user import User


class AddressMixin:
    """South African street address plus coordinates for 'nearby' search (UR-005)."""

    address_line: Mapped[str | None] = mapped_column(String(255))
    suburb: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    province: Mapped[str | None] = mapped_column(String(50))
    postal_code: Mapped[str | None] = mapped_column(String(10))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)


class ReviewMixin:
    """Admin approval fields (UR-004, SEC-003, SEC-043)."""

    verification_status: Mapped[VerificationStatus] = mapped_column(
        pg_enum(VerificationStatus, "verification_status"),
        default=VerificationStatus.PENDING,
        index=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class CustomerProfile(AddressMixin, TimestampMixin, Base):
    __tablename__ = "customer_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    user: Mapped["User"] = relationship(back_populates="customer_profile")


class DriverProfile(ReviewMixin, TimestampMixin, Base):
    __tablename__ = "driver_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # SA ID number (13 digits) or passport number for foreign nationals
    id_number: Mapped[str] = mapped_column(String(20), unique=True)
    vehicle_type: Mapped[VehicleType | None] = mapped_column(pg_enum(VehicleType, "vehicle_type"))
    vehicle_registration: Mapped[str | None] = mapped_column(String(20))
    # Drivers toggle this; only approved + available drivers see jobs (SEC-004)
    is_available: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    user: Mapped["User"] = relationship(back_populates="driver_profile", foreign_keys=[user_id])
    verified_by: Mapped["User | None"] = relationship(foreign_keys=[verified_by_id])


class BusinessProfile(AddressMixin, ReviewMixin, TimestampMixin, Base):
    __tablename__ = "business_profiles"
    # Speeds up the bounding-box step of "nearby" search (UR-005)
    __table_args__ = (Index("ix_business_profiles_lat_lng", "latitude", "longitude"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    # One business per owner account for now
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    business_name: Mapped[str] = mapped_column(String(150), index=True)
    registration_number: Mapped[str | None] = mapped_column(String(30), unique=True)  # CIPC
    description: Mapped[str | None] = mapped_column(Text)
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    # Public shop photo shown to customers (metadata stripped at upload)
    cover_photo_path: Mapped[str | None] = mapped_column(String(255))
    cover_photo_type: Mapped[str | None] = mapped_column(String(32))
    cover_photo_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    owner: Mapped["User"] = relationship(
        back_populates="business_profile", foreign_keys=[owner_user_id]
    )
    verified_by: Mapped["User | None"] = relationship(foreign_keys=[verified_by_id])
    staff: Mapped[list["BusinessStaff"]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    services: Mapped[list["LaundryService"]] = relationship(
        back_populates="business", cascade="all, delete-orphan",
        order_by="LaundryService.name",
    )


class BusinessStaff(TimestampMixin, Base):
    """Links a user account (role=business) to the laundry business they work at.

    Every person who touches laundry at a business has their own login, so
    handover records name the individual employee (SEC-017), and access is
    limited to that business's orders (Business Rule 8). The owner is also a
    row here with staff_role=owner. Staff don't need admin verification —
    the business itself is verified (SEC-043) and the owner vouches for staff.
    """

    __tablename__ = "business_staff"
    __table_args__ = (
        # At most one owner row per business
        Index(
            "uq_business_staff_one_owner",
            "business_id",
            unique=True,
            postgresql_where=text("staff_role = 'owner'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_profiles.id", ondelete="CASCADE"), index=True
    )
    # unique: a person works for one business at a time
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    staff_role: Mapped[BusinessStaffRole] = mapped_column(
        pg_enum(BusinessStaffRole, "business_staff_role")
    )
    # Deactivate instead of deleting, so past handover records stay linked
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    business: Mapped["BusinessProfile"] = relationship(back_populates="staff")
    user: Mapped["User"] = relationship(back_populates="staff_membership", foreign_keys=[user_id])
    added_by: Mapped["User | None"] = relationship(foreign_keys=[added_by_id])
