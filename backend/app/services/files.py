"""Shared handling for private uploaded files: ID documents and evidence photos.

* size limit enforced while reading;
* real type decided from the file's first bytes, never its name or header;
* SHA-256 fingerprint at upload, re-checked on every download (tamper detection);
* served with headers that stop browsers sniffing, caching or running content.
"""

import hashlib
import uuid
from typing import Any

from fastapi import HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.services import audit, storage

SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"%PDF-", "application/pdf", "pdf"),
]
IMAGE_TYPES = {"image/jpeg", "image/png"}


def read_limited(file: UploadFile) -> bytes:
    limit = settings.max_upload_mb * 1024 * 1024
    chunks, total = [], 0
    while chunk := file.file.read(1024 * 1024):
        total += len(chunk)
        if total > limit:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                f"File is larger than {settings.max_upload_mb} MB")
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "File is empty")
    return b"".join(chunks)


def detect(data: bytes) -> tuple[str, str] | None:
    for magic, mime, ext in SIGNATURES:
        if data.startswith(magic):
            return mime, ext
    return None


def read_image(file: UploadFile) -> tuple[bytes, str, str]:
    """Reads an upload that must be a JPEG or PNG photo. Returns (data, mime, ext)."""
    data = read_limited(file)
    detected = detect(data)
    if detected is None or detected[0] not in IMAGE_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            "Photos must be JPEG or PNG images")
    return data, *detected


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def serve(
    db: Session,
    *,
    path: str,
    expected_sha256: str,
    content_type: str,
    download_name: str,
    viewer: User,
    owner_id: uuid.UUID,
    action_prefix: str,
    entity_type: str,
    entity_id: Any,
    request: Request,
) -> Response:
    """Returns the file only if it's byte-for-byte what was uploaded. Viewing
    someone else's file is written to the audit log (POPIA access trail)."""
    data = storage.read(path)
    if data is None or sha256(data) != expected_sha256:
        audit.record(db, f"{action_prefix}.integrity_failed", actor_id=viewer.id,
                     entity_type=entity_type, entity_id=entity_id,
                     details={"file_missing": data is None}, request=request)
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This file failed its integrity check and may have been altered")
    if viewer.id != owner_id:
        audit.record(db, f"{action_prefix}.viewed", actor_id=viewer.id,
                     entity_type=entity_type, entity_id=entity_id, request=request)
        db.commit()
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="{download_name}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; sandbox",
            "Cache-Control": "no-store, private",
        },
    )
