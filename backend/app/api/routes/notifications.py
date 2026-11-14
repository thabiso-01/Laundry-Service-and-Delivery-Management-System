"""Your notification inbox (UR-016)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select, update

from app.api.deps import CurrentUser, DbSession
from app.models import Notification
from app.schemas.engagement import NotificationOut, NotificationPage

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _unread(db: DbSession, user_id) -> int:
    return db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user_id, Notification.read_at.is_(None)))


@router.get("", response_model=NotificationPage)
def my_notifications(
    user: CurrentUser, db: DbSession,
    unread_only: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> NotificationPage:
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    rows = db.scalars(query.order_by(Notification.created_at.desc(), Notification.id)
                      .limit(limit))
    return NotificationPage(items=[NotificationOut.model_validate(n) for n in rows],
                            unread=_unread(db, user.id))


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Notification:
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    if n.read_at is None:
        n.read_at = datetime.now(UTC)
        db.commit()
    return n


@router.post("/read-all")
def mark_all_read(user: CurrentUser, db: DbSession) -> dict:
    result = db.execute(update(Notification)
                        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
                        .values(read_at=datetime.now(UTC)))
    db.commit()
    return {"marked_read": result.rowcount}
