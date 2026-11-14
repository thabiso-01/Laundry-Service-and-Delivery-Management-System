"""Customer orders (UR-007, UR-008, SEC-009, SEC-042).

Money rules enforced by the database, not just the app:
  * order line prices are a snapshot taken when the order is placed, and
    order lines can never be edited or deleted afterwards (trigger);
  * line total = unit price × quantity, order total = subtotal + delivery fee
    (check constraints);
  * the status history is append-only (trigger).
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import OrderStatus, PricingUnit, ServiceCategory
from app.models.mixins import TimestampMixin, pg_enum, uuid_pk

if TYPE_CHECKING:
    from app.models.delivery import DeliveryJob, HandoverRecord
    from app.models.evidence import BagSeal
    from app.models.profiles import BusinessProfile
    from app.models.user import User


def _now() -> datetime:
    return datetime.now(UTC)


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("subtotal_cents > 0", name="subtotal_positive"),
        CheckConstraint("delivery_fee_cents >= 0", name="delivery_fee_not_negative"),
        CheckConstraint("total_cents = subtotal_cents + delivery_fee_cents", name="total_adds_up"),
        CheckConstraint("collection_window_end > collection_window_start",
                        name="collection_window_valid"),
        CheckConstraint("delivery_window_end > delivery_window_start",
                        name="delivery_window_valid"),
        CheckConstraint("delivery_window_start >= collection_window_end",
                        name="delivery_after_collection"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # Human-friendly, random (not sequential) reference, e.g. LC-7K3M9QX2 (SEC-009)
    order_number: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    # Bumped when a QR label is lost or copied; older codes stop working (SEC-010)
    qr_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_profiles.id"), index=True
    )
    status: Mapped[OrderStatus] = mapped_column(
        pg_enum(OrderStatus, "order_status"), default=OrderStatus.PLACED, index=True
    )

    # Address snapshot: later profile edits don't move an existing order
    collection_address_line: Mapped[str] = mapped_column(String(255))
    collection_suburb: Mapped[str | None] = mapped_column(String(100))
    collection_city: Mapped[str] = mapped_column(String(100))
    collection_province: Mapped[str | None] = mapped_column(String(50))
    collection_postal_code: Mapped[str | None] = mapped_column(String(10))
    collection_latitude: Mapped[float] = mapped_column(Float)
    collection_longitude: Mapped[float] = mapped_column(Float)

    delivery_address_line: Mapped[str] = mapped_column(String(255))
    delivery_suburb: Mapped[str | None] = mapped_column(String(100))
    delivery_city: Mapped[str] = mapped_column(String(100))
    delivery_province: Mapped[str | None] = mapped_column(String(50))
    delivery_postal_code: Mapped[str | None] = mapped_column(String(10))
    delivery_latitude: Mapped[float] = mapped_column(Float)
    delivery_longitude: Mapped[float] = mapped_column(Float)

    collection_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    collection_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivery_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivery_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    customer_notes: Mapped[str | None] = mapped_column(Text)

    # Money, in cents
    subtotal_cents: Mapped[int] = mapped_column(Integer)
    delivery_fee_cents: Mapped[int] = mapped_column(Integer)
    total_cents: Mapped[int] = mapped_column(Integer)
    distance_km: Mapped[float] = mapped_column(Float)
    # True when any line is priced per kg: the final weight is confirmed at the laundry
    is_estimate: Mapped[bool] = mapped_column(Boolean)

    cancelled_reason: Mapped[str | None] = mapped_column(Text)
    declined_reason: Mapped[str | None] = mapped_column(Text)

    # Money after the order was placed – only changed by verified payment
    # notifications and by weighing (SEC-042)
    paid_cents: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    adjustment_cents: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    weighed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def final_total_cents(self) -> int:
        return self.total_cents + self.adjustment_cents

    @property
    def balance_cents(self) -> int:
        """> 0: customer still owes this; < 0: refund due to the customer."""
        return self.final_total_cents - self.paid_cents

    customer: Mapped["User"] = relationship(foreign_keys=[customer_id])
    business: Mapped["BusinessProfile"] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", order_by="OrderItem.position"
    )
    events: Mapped[list["OrderStatusEvent"]] = relationship(
        back_populates="order", order_by="OrderStatusEvent.created_at"
    )
    jobs: Mapped[list["DeliveryJob"]] = relationship(
        back_populates="order", order_by="DeliveryJob.created_at"
    )
    handovers: Mapped[list["HandoverRecord"]] = relationship(
        order_by="HandoverRecord.created_at"
    )
    seals: Mapped[list["BagSeal"]] = relationship(order_by="BagSeal.recorded_at")


class OrderItem(Base):
    """One line of an order. Immutable once written."""

    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "service_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price_cents > 0", name="unit_price_positive"),
        CheckConstraint("line_total_cents = unit_price_cents * quantity", name="line_adds_up"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), index=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("laundry_services.id")
    )
    position: Mapped[int] = mapped_column(Integer)

    # Snapshot of the service at the time of ordering
    service_name: Mapped[str] = mapped_column(String(100))
    category: Mapped[ServiceCategory] = mapped_column(pg_enum(ServiceCategory, "service_category"))
    pricing_unit: Mapped[PricingUnit] = mapped_column(pg_enum(PricingUnit, "pricing_unit"))
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    turnaround_hours: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    line_total_cents: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")


class OrderStatusEvent(Base):
    """Append-only history of every status change: who, what, when (UR-012, SEC-017)."""

    __tablename__ = "order_status_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), index=True
    )
    from_status: Mapped[OrderStatus | None] = mapped_column(pg_enum(OrderStatus, "order_status"))
    to_status: Mapped[OrderStatus] = mapped_column(pg_enum(OrderStatus, "order_status"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), nullable=False
    )

    order: Mapped[Order] = relationship(back_populates="events")
    actor: Mapped["User | None"] = relationship()
