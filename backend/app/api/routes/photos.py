"""Photo evidence (SEC-029 – SEC-032). See app/services/photos.py for who may
add and view photos at each stage."""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response

from app.api.deps import CurrentUser, DbSession
from app.config import settings
from app.core.ratelimit import rate_limit
from app.models import EvidencePhoto
from app.models.enums import PhotoStage
from app.schemas.incidents import PhotoOut
from app.services import photos

router = APIRouter(prefix="/api/photos", tags=["photos"])


@router.post("", response_model=PhotoOut, status_code=status.HTTP_201_CREATED,
             # Drivers photograph many handovers, so photos get their own, larger budget
             dependencies=[rate_limit("photos", lambda: 2 * settings.ratelimit_reports_per_hour, 3600)])
def upload_photo(
    user: CurrentUser,
    db: DbSession,
    request: Request,
    stage: Annotated[PhotoStage, Form()],
    file: Annotated[UploadFile, File(description="JPEG or PNG, max 5 MB")],
    order_id: Annotated[uuid.UUID | None, Form()] = None,
    incident_id: Annotated[uuid.UUID | None, Form()] = None,
    caption: Annotated[str | None, Form(max_length=300)] = None,
) -> EvidencePhoto:
    """Attach a photo to an order handover (send order_id) or to your report
    (stage=incident, send incident_id)."""
    return photos.upload(db, user, stage=stage, file=file, caption=caption,
                         order_id=order_id, incident_id=incident_id, request=request)


@router.get("", response_model=list[PhotoOut])
def order_photos(
    user: CurrentUser, db: DbSession, order_id: Annotated[uuid.UUID, Query()],
) -> list[EvidencePhoto]:
    """Photos recorded for an order you're involved in."""
    return photos.for_order(db, user, order_id)


@router.get("/{photo_id}/file")
def photo_file(photo_id: uuid.UUID, user: CurrentUser, db: DbSession,
               request: Request) -> Response:
    photo = db.get(EvidencePhoto, photo_id)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    return photos.file_response(db, photo, user, request)
