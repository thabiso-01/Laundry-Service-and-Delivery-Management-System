import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import PricingUnit, ServiceCategory
from app.models.mixins import TimestampMixin, pg_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.profiles import BusinessProfile


class LaundryService(TimestampMixin, Base):
    """One priced service a laundry business offers (UR-006, Business Rule 11).

    Money is stored as whole cents (R85.50 → 8550) so no rounding errors creep
    in. Services are deactivated rather than deleted so past orders still point
    at what was offered.
    """

    __tablename__ = "laundry_services"
    __table_args__ = (
        UniqueConstraint("business_id", "name"),
        CheckConstraint("price_cents > 0", name="price_positive"),
        CheckConstraint("turnaround_hours > 0", name="turnaround_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[ServiceCategory] = mapped_column(
        pg_enum(ServiceCategory, "service_category"), index=True
    )
    pricing_unit: Mapped[PricingUnit] = mapped_column(pg_enum(PricingUnit, "pricing_unit"))
    price_cents: Mapped[int] = mapped_column(Integer)
    # Smallest order for this service, e.g. "minimum 3 kg" (in the pricing unit)
    min_quantity: Mapped[int] = mapped_column(Integer, default=1)
    turnaround_hours: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    business: Mapped["BusinessProfile"] = relationship(back_populates="services")
