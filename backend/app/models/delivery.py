"""Driver jobs, one-time codes and handover records (UR-009, SEC-005 – SEC-017, SEC-022)."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import HandoverKind, HandoverMethod, JobKind, JobStatus, OtpPurpose
from app.models.mixins import TimestampMixin, pg_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.orders import Order
    from app.models.user import User


def _now() -> datetime:
    return datetime.now(UTC)


class DeliveryJob(TimestampMixin, Base):
    """One driver trip for an order: collection or delivery."""

    __tablename__ = "delivery_jobs"
    __table_args__ = (UniqueConstraint("order_id", "kind"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), index=True
    )
    kind: Mapped[JobKind] = mapped_column(pg_enum(JobKind, "job_kind"))
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"), default=JobStatus.OPEN, index=True
    )
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    driver_fee_cents: Mapped[int] = mapped_column(Integer)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped["Order"] = relationship(back_populates="jobs")
    driver: Mapped["User | None"] = relationship()


class OrderOtp(Base):
    """A one-time code the customer gives the driver (SEC-005 – SEC-008).

    The code itself is never stored: it's derived from this row's random id
    with a server-side key, so a database leak doesn't reveal live codes.
    """

    __tablename__ = "order_otps"
    __table_args__ = (
        # At most one live code per order and purpose
        Index("uq_order_otps_one_active", "order_id", "purpose", unique=True,
              postgresql_where=text("used_at IS NULL AND revoked_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), index=True
    )
    purpose: Mapped[OtpPurpose] = mapped_column(pg_enum(OtpPurpose, "otp_purpose"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )


class HandoverRecord(Base):
    """Permanent record of who handed the laundry to whom, when, where and how
    it was verified (SEC-013 – SEC-017, SEC-022). Append-only (trigger)."""

    __tablename__ = "handover_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("delivery_jobs.id"))
    kind: Mapped[HandoverKind] = mapped_column(pg_enum(HandoverKind, "handover_kind"))
    method: Mapped[HandoverMethod] = mapped_column(pg_enum(HandoverMethod, "handover_method"))
    from_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"))
    to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"))
    # Driver's GPS position at the handover, and how far that is from where it should be
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    distance_from_expected_m: Mapped[float | None] = mapped_column(Float)
    location_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    from_user: Mapped["User | None"] = relationship(foreign_keys=[from_user_id])
    to_user: Mapped["User | None"] = relationship(foreign_keys=[to_user_id])
