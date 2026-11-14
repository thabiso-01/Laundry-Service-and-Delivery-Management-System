"""The single place an order's status changes, so history is never skipped (SEC-017)."""

from sqlalchemy.orm import Session

from app.models import Order, OrderStatusEvent, User
from app.models.enums import OrderStatus


def change_status(
    db: Session, order: Order, to: OrderStatus, actor: User | None, note: str | None = None
) -> None:
    # Append through the relationship so order.events is never stale in memory
    order.events.append(OrderStatusEvent(from_status=order.status, to_status=to,
                                         actor_user_id=actor.id if actor else None, note=note))
    order.status = to


def label(s: OrderStatus) -> str:
    return s.value.replace("_", " ")
