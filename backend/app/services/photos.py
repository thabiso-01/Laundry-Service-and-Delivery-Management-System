"""Photo evidence at handovers and on incidents (SEC-029 – SEC-032).

Who may add a photo, and at which stage:
    driver   – collection (collection job); pickup / delivery (delivery job),
               only while the job is theirs and active
    business – receipt / pickup, only for their own business's orders
    anyone   – incident, only on a report they made (admins: any report)

Who may view: the order's parties (Business Rules 7 – 9) and admins. Admin
views are written to the audit log.
"""

import uuid

from fastapi import HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DeliveryJob, EvidencePhoto, Incident, Order, User
from app.models.enums import JobKind, JobStatus, PhotoStage, UserRole
from app.services import audit, files, storage
from app.services.incidents import is_party

_DRIVER_STAGES = {
    JobKind.COLLECTION: {PhotoStage.COLLECTION},
    JobKind.DELIVERY: {PhotoStage.PICKUP, PhotoStage.DELIVERY},
}
_BUSINESS_STAGES = {PhotoStage.RECEIPT, PhotoStage.PICKUP}
_ACTIVE = (JobStatus.ASSIGNED, JobStatus.PICKED_UP)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail)


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


def _driver_job(user: User, order: Order, stage: PhotoStage) -> DeliveryJob:
    for job in order.jobs:
        if (job.driver_id == user.id and job.status in _ACTIVE
                and stage in _DRIVER_STAGES[job.kind]):
            return job
    raise _forbidden("You can only add photos for this stage of a job you're doing")


def upload(
    db: Session, user: User, *, stage: PhotoStage, file: UploadFile, caption: str | None,
    order_id: uuid.UUID | None, incident_id: uuid.UUID | None, request: Request,
) -> EvidencePhoto:
    order: Order | None = None
    incident: Incident | None = None
    job: DeliveryJob | None = None

    if stage == PhotoStage.INCIDENT:
        incident = db.get(Incident, incident_id) if incident_id else None
        if incident is None or (user.role != UserRole.ADMIN
                                and incident.reported_by_id != user.id):
            raise _not_found("Report")
        order = incident.order
    else:
        order = db.get(Order, order_id) if order_id else None
        if order is None or not is_party(user, order):
            raise _not_found("Order")
        if user.role == UserRole.DRIVER:
            job = _driver_job(user, order, stage)
        elif user.role == UserRole.BUSINESS:
            if stage not in _BUSINESS_STAGES:
                raise _forbidden("Laundries add photos when receiving or handing over laundry")
        else:
            raise _forbidden("Attach photos to a report instead")

    data, mime, ext = files.read_image(file)
    photo_id = uuid.uuid4()
    folder = f"photos/{order.id if order else 'incidents'}"
    path = storage.save(folder, f"{photo_id}.{ext}", data)
    try:
        photo = EvidencePhoto(
            id=photo_id, order_id=order.id if order else None,
            incident_id=incident.id if incident else None, job_id=job.id if job else None,
            stage=stage, uploaded_by_id=user.id, uploader_role=user.role,
            file_path=path, content_type=mime, file_size=len(data),
            sha256=files.sha256(data), caption=caption,
        )
        db.add(photo)
        audit.record(db, "photo.uploaded", actor_id=user.id, entity_type="evidence_photo",
                     entity_id=photo_id,
                     details={"stage": stage.value,
                              "order_number": order.order_number if order else None,
                              "incident": incident.reference if incident else None},
                     request=request)
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(path)
        raise
    return photo


def can_view(user: User, photo: EvidencePhoto, db: Session) -> bool:
    if user.role == UserRole.ADMIN or photo.uploaded_by_id == user.id:
        return True
    if photo.order_id:
        order = db.get(Order, photo.order_id)
        return order is not None and is_party(user, order)
    return False


def for_order(db: Session, user: User, order_id: uuid.UUID) -> list[EvidencePhoto]:
    order = db.get(Order, order_id)
    if order is None or not (user.role == UserRole.ADMIN or is_party(user, order)):
        raise _not_found("Order")
    return list(db.scalars(select(EvidencePhoto).where(EvidencePhoto.order_id == order_id)
                           .order_by(EvidencePhoto.created_at)))


def file_response(db: Session, photo: EvidencePhoto, viewer: User, request: Request) -> Response:
    if not can_view(viewer, photo, db):
        raise _not_found("Photo")
    ext = photo.file_path.rsplit(".", 1)[-1]
    return files.serve(
        db, path=photo.file_path, expected_sha256=photo.sha256,
        content_type=photo.content_type, download_name=f"{photo.stage.value}.{ext}",
        viewer=viewer, owner_id=photo.uploaded_by_id, action_prefix="photo",
        entity_type="evidence_photo", entity_id=photo.id, request=request,
    )
