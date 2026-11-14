import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


def uuid_pk() -> Mapped[uuid.UUID]:
    # UUIDs instead of 1,2,3… so IDs can't be guessed or enumerated
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """Native Postgres enum that stores the lower-case .value, not the NAME."""
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
