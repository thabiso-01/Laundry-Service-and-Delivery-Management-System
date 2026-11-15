"""Payments, weighing adjustments, notifications, reviews and live driver
locations (Phase 5: UR-014, UR-016, SEC-021 – SEC-024, SEC-042)."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import PaymentStatus, ReviewTarget
from app.models.mixins import TimestampMixin, pg_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.user import User


def _now() -> datetime:
    return datetime.now(UTC)


class Payment(TimestampMixin, Base):
    """One checkout attempt for an order (the initial amount or a balance)."""

    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount_cents > 0", name="amount_positive"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), index=True)
    # Our reference, sent to the provider and echoed back in its notifications
    reference: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(20))
    status: Mapped[PaymentStatus] = mapped_column(
        pg_enum(PaymentStatus, "payment_status"), default=PaymentStatus.PENDING, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    provider_payment_id: Mapped[str | None] = mapped_column(String(100))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentEvent(Base):
    """Every notification received from the payment provider, valid or not.
    Append-only (trigger): the evidence trail for disputes (SEC-042)."""

    __tablename__ = "payment_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), index=True)
    reference: Mapped[str | None] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(40))  # applied, duplicate, bad_signature, …
    signature_valid: Mapped[bool] = mapped_column(Boolean)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now())


class OrderAdjustment(Base):
    """Price change after the laundry weighs a per-kg line (append-only).
    The original order lines stay untouched; this records the difference."""

    __tablename__ = "order_adjustments"

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), index=True)
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_items.id"))
    estimated_quantity: Mapped[int] = mapped_column(Integer)
    actual_quantity: Mapped[int] = mapped_column(Integer)
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)  # + customer owes more, − refund due
    recorded_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now())


class Notification(Base):
    """An in-app message (UR-016). SMS/e-mail delivery plugs in later."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_unread", "user_id", "read_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(150))
    body: Mapped[str] = mapped_column(Text)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"))
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), index=True)

    # SMS outbox: sent by a background worker after the transaction commits
    # None = in-app only; pending → sent | failed | skipped
    sms_status: Mapped[str | None] = mapped_column(String(20), index=True)
    sms_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sms_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sms_provider_id: Mapped[str | None] = mapped_column(String(100))
    sms_error: Mapped[str | None] = mapped_column(String(300))


class Review(Base):
    """A customer's rating of a laundry or a driver after delivery (UR-014)."""

    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
        # One laundry review per order, one driver review per trip
        Index("uq_reviews_business_per_order", "order_id", unique=True,
              postgresql_where=text("target = 'business'")),
        Index("uq_reviews_driver_per_job", "job_id", unique=True,
              postgresql_where=text("target = 'driver'")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    target: Mapped[ReviewTarget] = mapped_column(pg_enum(ReviewTarget, "review_target"))
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_profiles.id"), index=True)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_jobs.id"))
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now())

    customer: Mapped["User"] = relationship(foreign_keys=[customer_id])


class DriverLocation(Base):
    """A GPS ping from a driver during an active job (SEC-021 – SEC-024)."""

    __tablename__ = "driver_locations"
    __table_args__ = (Index("ix_driver_locations_job_time", "job_id", "recorded_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_jobs.id"))
    driver_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    # Carrying laundry well away from the direct route (SEC-024)
    off_route: Mapped[bool] = mapped_column(Boolean, default=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now())
