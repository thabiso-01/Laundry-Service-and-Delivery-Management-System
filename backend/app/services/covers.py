"""Public shop photos for laundries (shown on search results and the laundry page).

Unlike ID documents and evidence photos these are meant to be public, so they
are served without a login – but only for approved laundries. Hidden metadata
(EXIF: GPS position, camera serial, date; XMP; IPTC; PNG text chunks) is
removed before the file is stored, so a photo taken on a phone can't leak more
than what's visible in it.
"""

import struct
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.models import BusinessProfile, User
from app.services import audit, files, storage

FOLDER = "covers"


# ---------- Metadata stripping ----------

# JPEG segments that only carry metadata: APP1 (EXIF/XMP), APP3-APP13 (incl.
# IPTC/Photoshop in APP13), APP15 and comments. APP0 (JFIF), APP2 (colour
# profile) and APP14 (Adobe colour transform) are kept so the image looks right.
_JPEG_DROP = {0xE1, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xEB, 0xEC, 0xED, 0xEF, 0xFE}


def _strip_jpeg(data: bytes) -> bytes:
    out = bytearray(data[:2])  # SOI
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            raise ValueError("Broken JPEG")
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan: the rest is image data
            out += data[i:]
            return bytes(out)
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        segment = data[i:i + 2 + length]
        if len(segment) < 2 + length:
            raise ValueError("Broken JPEG")
        if marker not in _JPEG_DROP:
            out += segment
        i += 2 + length
    raise ValueError("Broken JPEG")


# PNG chunks that only carry metadata
_PNG_DROP = {b"eXIf", b"tEXt", b"iTXt", b"zTXt", b"tIME"}


def _strip_png(data: bytes) -> bytes:
    out = bytearray(data[:8])
    i = 8
    while i + 12 <= len(data):
        length = struct.unpack(">I", data[i:i + 4])[0]
        kind = data[i + 4:i + 8]
        chunk = data[i:i + 12 + length]
        if len(chunk) < 12 + length:
            raise ValueError("Broken PNG")
        if kind not in _PNG_DROP:
            out += chunk
        i += 12 + length
        if kind == b"IEND":
            return bytes(out)
    raise ValueError("Broken PNG")


def strip_metadata(data: bytes, mime: str) -> bytes:
    try:
        return _strip_jpeg(data) if mime == "image/jpeg" else _strip_png(data)
    except (ValueError, struct.error):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That image file looks damaged")


# ---------- Upload, remove, serve ----------

def photo_url(business: BusinessProfile) -> str | None:
    if not business.cover_photo_path or not business.cover_photo_updated_at:
        return None
    # The version makes browsers fetch the new photo after a change
    return f"/api/laundries/{business.id}/photo?v={int(business.cover_photo_updated_at.timestamp())}"


def upload(db: Session, business: BusinessProfile, file: UploadFile, actor: User, request: Request) -> None:
    data, mime, ext = files.read_image(file)
    clean = strip_metadata(data, mime)
    old = business.cover_photo_path
    business.cover_photo_path = storage.save(FOLDER, f"{uuid.uuid4()}.{ext}", clean)
    business.cover_photo_type = mime
    business.cover_photo_updated_at = datetime.now(UTC)
    audit.record(db, "business.photo_updated", actor_id=actor.id, entity_type="business_profile",
                 entity_id=business.id, details={"bytes": len(clean)}, request=request)
    db.commit()
    if old:
        storage.delete(old)


def remove(db: Session, business: BusinessProfile, actor: User, request: Request) -> None:
    old = business.cover_photo_path
    if not old:
        return
    business.cover_photo_path = business.cover_photo_type = business.cover_photo_updated_at = None
    audit.record(db, "business.photo_removed", actor_id=actor.id, entity_type="business_profile",
                 entity_id=business.id, request=request)
    db.commit()
    storage.delete(old)


def serve(business: BusinessProfile) -> Response:
    data = storage.read(business.cover_photo_path) if business.cover_photo_path else None
    if data is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No photo")
    return Response(content=data, media_type=business.cover_photo_type or "image/jpeg", headers={
        "Cache-Control": "public, max-age=86400",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    })
