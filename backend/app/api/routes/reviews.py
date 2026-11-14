"""Ratings and reviews (UR-014)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import AdminUser, ApprovedDriver, CustomerUser, DbSession, require_admin
from app.api.routes.orders import _own_order
from app.models import Review
from app.models.enums import ReviewTarget
from app.schemas.engagement import (
    DriverRatingsOut,
    HideReviewIn,
    RatingSummaryOut,
    ReviewIn,
    ReviewOut,
)
from app.services import audit, reviews
from app.services.search import get_bookable

router = APIRouter(tags=["reviews"])


def review_out(r: Review) -> ReviewOut:
    return ReviewOut(id=r.id, target=r.target, rating=r.rating, comment=r.comment,
                     reviewer=r.customer.full_name.split()[0], created_at=r.created_at)


@router.post("/api/orders/{order_id}/reviews", response_model=ReviewOut,
             status_code=status.HTTP_201_CREATED)
def review_order(order_id: uuid.UUID, body: ReviewIn, customer: CustomerUser, db: DbSession,
                 request: Request) -> ReviewOut:
    """Rate the laundry (target=business) or a driver (target=driver + job_id)."""
    order = _own_order(db, customer, order_id)
    review = reviews.create(db, order, customer, body.target, body.job_id, body.rating,
                            body.comment, request)
    return review_out(review)


@router.get("/api/laundries/{business_id}/reviews", response_model=list[ReviewOut])
def laundry_reviews(
    business_id: uuid.UUID, db: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReviewOut]:
    """Public reviews of a laundry, newest first."""
    if get_bookable(db, business_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Laundry not found")
    rows = db.scalars(select(Review).where(
        Review.business_id == business_id, Review.target == ReviewTarget.BUSINESS,
        Review.is_hidden.is_(False)).order_by(Review.created_at.desc()).limit(limit).offset(offset))
    return [review_out(r) for r in rows]


@router.get("/api/driver/ratings", response_model=DriverRatingsOut)
def my_driver_ratings(driver: ApprovedDriver, db: DbSession) -> DriverRatingsOut:
    avg, count = reviews.summary(db, Review.target == ReviewTarget.DRIVER,
                                 Review.driver_id == driver.user_id)
    recent = db.scalars(select(Review).where(
        Review.target == ReviewTarget.DRIVER, Review.driver_id == driver.user_id,
        Review.is_hidden.is_(False)).order_by(Review.created_at.desc()).limit(10))
    return DriverRatingsOut(rating_avg=avg, rating_count=count,
                            recent=[review_out(r) for r in recent])


admin = APIRouter(prefix="/api/admin", tags=["admin: reviews"],
                  dependencies=[Depends(require_admin)])


@admin.post("/reviews/{review_id}/hide", response_model=RatingSummaryOut)
def hide_review(review_id: uuid.UUID, body: HideReviewIn, admin_user: AdminUser, db: DbSession,
                request: Request) -> RatingSummaryOut:
    """Hide an abusive or fake review. It stops counting towards the rating."""
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
    review.is_hidden = True
    review.hidden_reason = body.reason
    audit.record(db, "review.hidden", actor_id=admin_user.id, entity_type="review",
                 entity_id=review.id, details={"reason": body.reason}, request=request)
    db.commit()
    avg, count = reviews.summary(db, Review.target == review.target,
                                 Review.business_id == review.business_id
                                 if review.target == ReviewTarget.BUSINESS
                                 else Review.driver_id == review.driver_id)
    return RatingSummaryOut(rating_avg=avg, rating_count=count)
