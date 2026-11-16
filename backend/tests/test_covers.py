"""Laundry shop photos: upload by owners/managers, metadata stripped, public
only for approved laundries."""

import struct

import pytest

from app.models.enums import BusinessStaffRole, VerificationStatus
from app.services import covers, storage
from tests.conftest import auth_header


def _segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


GPS = b"Exif\x00\x00GPS-LAT-26.19-LNG-28.03"
# SOI, JFIF, EXIF with "GPS", ICC profile, a comment, then image data
JPEG = (b"\xff\xd8" + _segment(0xE0, b"JFIF\x00\x01\x01") + _segment(0xE1, GPS)
        + _segment(0xE2, b"ICC_PROFILE\x00x") + _segment(0xFE, b"taken by Pieter")
        + b"\xff\xda" + b"\x00\x08pixels\xff\xd9")


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + b"\x00\x00\x00\x00"


PNG = (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", b"\x00" * 13) + _png_chunk(b"tEXt", b"Author\x00Pieter")
       + _png_chunk(b"eXIf", GPS) + _png_chunk(b"IDAT", b"pixels") + _png_chunk(b"IEND", b""))


def test_jpeg_metadata_is_removed_and_image_kept():
    clean = covers.strip_metadata(JPEG, "image/jpeg")
    assert b"GPS" not in clean and b"Pieter" not in clean
    assert b"JFIF" in clean and b"ICC_PROFILE" in clean and clean.endswith(b"pixels\xff\xd9")


def test_png_metadata_is_removed_and_image_kept():
    clean = covers.strip_metadata(PNG, "image/png")
    assert b"GPS" not in clean and b"Pieter" not in clean
    assert b"IHDR" in clean and b"IDAT" in clean and b"IEND" in clean


def test_damaged_image_is_refused(client, make_laundry):
    biz = make_laundry()
    r = client.post("/api/business/profile/photo", headers=auth_header(biz.owner),
                    files={"file": ("x.jpg", b"\xff\xd8\xff\xe1\x00", "image/jpeg")})
    assert r.status_code == 422


def test_owner_uploads_photo_and_customers_see_it(client, make_laundry):
    biz = make_laundry()
    r = client.post("/api/business/profile/photo", headers=auth_header(biz.owner),
                    files={"file": ("shop.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200, r.text
    url = r.json()["photo_url"]
    assert url.startswith(f"/api/laundries/{biz.id}/photo?v=")

    # Shown in search results and on the laundry page
    found = client.get("/api/laundries", params={"lat": -26.19, "lng": 28.03}).json()["items"]
    assert [i["photo_url"] for i in found if i["id"] == str(biz.id)] == [url]
    assert client.get(f"/api/laundries/{biz.id}").json()["photo_url"] == url

    # Public, no login, without the hidden metadata
    photo = client.get(url)
    assert photo.status_code == 200
    assert photo.headers["content-type"] == "image/jpeg"
    assert photo.headers["x-content-type-options"] == "nosniff"
    assert b"GPS" not in photo.content and photo.content.endswith(b"pixels\xff\xd9")


def test_replacing_and_removing_deletes_old_files(client, make_laundry, db):
    biz = make_laundry()
    h = auth_header(biz.owner)
    client.post("/api/business/profile/photo", headers=h, files={"file": ("a.jpg", JPEG, "image/jpeg")})
    first = biz.cover_photo_path
    client.post("/api/business/profile/photo", headers=h, files={"file": ("b.png", PNG, "image/png")})
    assert biz.cover_photo_path != first and storage.read(first) is None
    assert client.get(f"/api/laundries/{biz.id}/photo").headers["content-type"] == "image/png"

    second = biz.cover_photo_path
    r = client.delete("/api/business/profile/photo", headers=h)
    assert r.status_code == 200 and r.json()["photo_url"] is None
    assert storage.read(second) is None
    assert client.get(f"/api/laundries/{biz.id}/photo").status_code == 404


def test_only_images_are_accepted(client, make_laundry):
    biz = make_laundry()
    r = client.post("/api/business/profile/photo", headers=auth_header(biz.owner),
                    files={"file": ("menu.pdf", b"%PDF-1.4 hello", "application/pdf")})
    assert r.status_code == 415


@pytest.mark.parametrize("role, allowed", [
    (BusinessStaffRole.MANAGER, True), (BusinessStaffRole.ATTENDANT, False)])
def test_attendants_cannot_change_the_photo(client, make_laundry, add_staff, role, allowed):
    biz = make_laundry()
    staff = add_staff(biz, role)
    r = client.post("/api/business/profile/photo", headers=auth_header(staff),
                    files={"file": ("shop.jpg", JPEG, "image/jpeg")})
    assert (r.status_code == 200) is allowed


def test_unapproved_laundry_photo_is_not_public(client, make_business, db):
    biz = make_business(VerificationStatus.PENDING)
    r = client.post("/api/business/profile/photo", headers=auth_header(biz.owner),
                    files={"file": ("shop.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 200  # can prepare it before approval
    assert client.get(f"/api/laundries/{biz.id}/photo").status_code == 404
