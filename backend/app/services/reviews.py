"""Ratings and reviews (UR-014).

Only the order's customer, only after delivery, only within the review
window, and once per laundry per order and once per driver per trip.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Order, Review, User
from app.models.enums import OrderStatus, ReviewTarget
from app.services import audit


def create(db: Session, order: Order, customer: User, target: ReviewTarget,
           job_id: uuid.UUID | None, rating: int, comment: str | None,
           request: Request) -> Review:
    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(status.HTTP_409_CONFLICT, "You can review an order once it's delivered")
    delivered_at = max((e.created_at for e in order.events
                        if e.to_status == OrderStatus.DELIVERED), default=None)
    if delivered_at and datetime.now(UTC) - delivered_at > timedelta(
            days=settings.review_window_days):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Reviews close {settings.review_window_days} days after delivery")

    driver_id = None
    if target == ReviewTarget.DRIVER:
        job = next((j for j in order.jobs if j.id == job_id and j.driver_id), None)
        if job is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Choose one of this order's trips to rate its driver")
        driver_id = job.driver_id
        duplicate = select(Review.id).where(Review.target == target, Review.job_id == job_id)
    else:
        if job_id is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "job_id is only for driver reviews")
        duplicate = select(Review.id).where(Review.target == target, Review.order_id == order.id)
    if db.scalar(duplicate):
        raise HTTPException(status.HTTP_409_CONFLICT, "You've already left this review")

    review = Review(order_id=order.id, customer_id=customer.id, target=target,
                    business_id=order.business_id, driver_id=driver_id, job_id=job_id,
                    rating=rating, comment=comment)
    db.add(review)
    db.flush()
    audit.record(db, "review.created", actor_id=customer.id, entity_type="review",
                 entity_id=review.id,
                 details={"order_number": order.order_number, "target": target.value,
                          "rating": rating},
                 request=request)
    db.commit()
    return review


def business_rating_subquery():
    """(business_id, avg, count) over visible business reviews – for search."""
    return (select(Review.business_id,
                   func.avg(Review.rating).label("rating_avg"),
                   func.count().label("rating_count"))
            .where(Review.target == ReviewTarget.BUSINESS, Review.is_hidden.is_(False))
            .group_by(Review.business_id).subquery())


def summary(db: Session, *where) -> tuple[float | None, int]:
    avg, count = db.execute(select(func.avg(Review.rating), func.count())
                            .where(Review.is_hidden.is_(False), *where)).one()
    return (round(float(avg), 2) if avg is not None else None), count
