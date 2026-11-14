"""Seals, photo evidence and incidents (SEC-025 – SEC-037, SEC-048, UR-015)."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentStatus,
    JobKind,
    PhotoStage,
    SealCheck,
    UserRole,
)
from app.models.mixins import TimestampMixin, pg_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.orders import Order
    from app.models.user import User


def _now() -> datetime:
    return datetime.now(UTC)


class BagSeal(Base):
    """A numbered tamper-evident seal on a laundry bag (SEC-025 – SEC-027).

    Seal numbers are unique across the whole platform, so an old seal can't be
    reused to make a re-opened bag look untouched.
    """

    __tablename__ = "bag_seals"

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), index=True)
    leg: Mapped[JobKind] = mapped_column(pg_enum(JobKind, "job_kind"))
    seal_number: Mapped[str] = mapped_column(String(20), unique=True)
    recorded_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now())
    # Filled in at the end of the trip
    check_result: Mapped[SealCheck | None] = mapped_column(pg_enum(SealCheck, "seal_check"))
    checked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Incident(TimestampMixin, Base):
    """A reported problem, investigated by an administrator (SEC-033 – SEC-037)."""

    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = uuid_pk()
    reference: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # SEC-035
    # Optional: fraud reports may not concern a particular order
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), index=True)
    reported_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    reporter_role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, "user_role"))
    # True when the system opened it, e.g. after a failed seal check
    is_automatic: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[IncidentCategory] = mapped_column(
        pg_enum(IncidentCategory, "incident_category"), index=True)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[IncidentStatus] = mapped_column(
        pg_enum(IncidentStatus, "incident_status"), default=IncidentStatus.OPEN, index=True)
    severity: Mapped[IncidentSeverity] = mapped_column(
        pg_enum(IncidentSeverity, "incident_severity"), default=IncidentSeverity.MEDIUM)
    assigned_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"))
    resolution: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped["Order | None"] = relationship()
    reported_by: Mapped["User"] = relationship(foreign_keys=[reported_by_id])
    assigned_admin: Mapped["User | None"] = relationship(foreign_keys=[assigned_admin_id])
    updates: Mapped[list["IncidentUpdate"]] = relationship(
        back_populates="incident", order_by="IncidentUpdate.created_at")


class IncidentUpdate(Base):
    """Append-only investigation trail: comments and status changes (SEC-037)."""

    __tablename__ = "incident_updates"

    id: Mapped[uuid.UUID] = uuid_pk()
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id"), index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"))
    from_status: Mapped[IncidentStatus | None] = mapped_column(
        pg_enum(IncidentStatus, "incident_status"))
    to_status: Mapped[IncidentStatus | None] = mapped_column(
        pg_enum(IncidentStatus, "incident_status"))
    note: Mapped[str | None] = mapped_column(Text)
    # Admin-only notes are never shown to the reporter
    internal: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now())

    incident: Mapped[Incident] = relationship(back_populates="updates")
    author: Mapped["User | None"] = relationship()


class EvidencePhoto(Base):
    """A photo taken at a handover or attached to an incident (SEC-029 – SEC-032).
    Stored privately like ID documents; rows are append-only."""

    __tablename__ = "evidence_photos"

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), index=True)
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incidents.id"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("delivery_jobs.id"))
    stage: Mapped[PhotoStage] = mapped_column(pg_enum(PhotoStage, "photo_stage"))
    uploaded_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    uploader_role: Mapped[UserRole] = mapped_column(pg_enum(UserRole, "user_role"))
    file_path: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    caption: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now())

    uploaded_by: Mapped["User"] = relationship()
