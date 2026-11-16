"""A laundry business manages its own profile and service catalog
(UR-003, UR-006, Business Rule 8 & 11).

Everything is scoped to the caller's own business: another business's
services return 404, as if they didn't exist.

A pending (not yet verified) business can already set up its profile and
catalog, so it's ready the moment it's approved. Customers only see it
after approval.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, require_business_staff
from app.models import BusinessProfile, BusinessStaff, LaundryService
from app.models.enums import BusinessStaffRole
from app.schemas.business import (
    BusinessProfileOut,
    BusinessProfileUpdate,
    ServiceIn,
    ServiceOut,
    ServiceUpdate,
)
from app.services import audit, covers

router = APIRouter(prefix="/api/business", tags=["business"])

# Any active staff member may look; managers and owners may change things
AnyStaff = Annotated[
    BusinessStaff, Depends(require_business_staff(business_must_be_verified=False))
]
Manager = Annotated[
    BusinessStaff,
    Depends(require_business_staff(BusinessStaffRole.MANAGER, business_must_be_verified=False)),
]

DUPLICATE_NAME = "Your business already has a service with this name"


# ---------- Profile ----------

def _profile_out(business: BusinessProfile) -> BusinessProfileOut:
    out = BusinessProfileOut.model_validate(business)
    out.photo_url = covers.photo_url(business)
    return out


@router.get("/profile", response_model=BusinessProfileOut)
def get_profile(staff: AnyStaff) -> BusinessProfileOut:
    return _profile_out(staff.business)


@router.patch("/profile", response_model=BusinessProfileOut)
def update_profile(
    body: BusinessProfileUpdate, staff: Manager, db: DbSession, request: Request
) -> BusinessProfileOut:
    business = staff.business
    changes = audit.apply_changes(business, body.model_dump(exclude_unset=True))
    if changes:
        audit.record(db, "business.profile_updated", actor_id=staff.user_id,
                     entity_type="business_profile", entity_id=business.id,
                     details=changes, request=request)
        db.commit()
    return _profile_out(business)


@router.post("/profile/photo", response_model=BusinessProfileOut)
def upload_photo(
    staff: Manager, db: DbSession, request: Request, file: UploadFile = File(...)
) -> BusinessProfileOut:
    """Public shop photo (JPEG or PNG, max 5 MB). Hidden metadata such as GPS is removed."""
    covers.upload(db, staff.business, file, staff.user, request)
    return _profile_out(staff.business)


@router.delete("/profile/photo", response_model=BusinessProfileOut)
def remove_photo(staff: Manager, db: DbSession, request: Request) -> BusinessProfileOut:
    covers.remove(db, staff.business, staff.user, request)
    return _profile_out(staff.business)


# ---------- Services ----------

def _own_service(db: DbSession, staff: BusinessStaff, service_id: uuid.UUID) -> LaundryService:
    service = db.get(LaundryService, service_id, with_for_update=True)
    if service is None or service.business_id != staff.business_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Service not found")
    return service


def _commit_or_conflict(db: DbSession) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, DUPLICATE_NAME)


@router.get("/services", response_model=list[ServiceOut])
def list_services(
    staff: AnyStaff,
    db: DbSession,
    include_inactive: Annotated[bool, Query()] = False,
) -> list[LaundryService]:
    query = select(LaundryService).where(LaundryService.business_id == staff.business_id)
    if not include_inactive:
        query = query.where(LaundryService.is_active.is_(True))
    return list(db.scalars(query.order_by(LaundryService.category, LaundryService.name)))


@router.post("/services", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
def create_service(
    body: ServiceIn, staff: Manager, db: DbSession, request: Request
) -> LaundryService:
    service = LaundryService(business_id=staff.business_id, **body.model_dump())
    db.add(service)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, DUPLICATE_NAME)
    audit.record(db, "service.created", actor_id=staff.user_id, entity_type="laundry_service",
                 entity_id=service.id,
                 details={"name": service.name, "price_cents": service.price_cents,
                          "pricing_unit": service.pricing_unit.value},
                 request=request)
    _commit_or_conflict(db)
    return service


@router.patch("/services/{service_id}", response_model=ServiceOut)
def update_service(
    service_id: uuid.UUID, body: ServiceUpdate, staff: Manager, db: DbSession, request: Request
) -> LaundryService:
    """Change a service. Price changes are recorded with old and new values (SEC-042)."""
    service = _own_service(db, staff, service_id)
    changes = audit.apply_changes(service, body.model_dump(exclude_unset=True))
    if changes:
        audit.record(db, "service.updated", actor_id=staff.user_id,
                     entity_type="laundry_service", entity_id=service.id,
                     details=changes, request=request)
        _commit_or_conflict(db)
    return service


@router.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_service(
    service_id: uuid.UUID, staff: Manager, db: DbSession, request: Request
) -> Response:
    """Hides the service from customers. It's kept (not deleted) so past orders
    still show what was ordered; reactivate it with PATCH is_active=true."""
    service = _own_service(db, staff, service_id)
    if service.is_active:
        service.is_active = False
        audit.record(db, "service.deactivated", actor_id=staff.user_id,
                     entity_type="laundry_service", entity_id=service.id,
                     details={"name": service.name}, request=request)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
