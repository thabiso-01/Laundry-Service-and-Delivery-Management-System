"""Private file storage for uploaded documents.

Files live on local disk under settings.upload_dir, named by random UUID so a
user-supplied filename never reaches the filesystem. Only the relative path is
stored in the database. Swap this module for S3/Azure storage later without
touching the routes.
"""

from pathlib import Path

from app.config import settings


def _base() -> Path:
    base = Path(settings.upload_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _resolve(relative_path: str) -> Path:
    base = _base()
    path = (base / relative_path).resolve()
    # Defence in depth: refuse anything that escapes the upload folder
    if not path.is_relative_to(base):
        raise ValueError("Invalid storage path")
    return path


def save(folder: str, filename: str, data: bytes) -> str:
    relative = f"{folder}/{filename}"
    path = _resolve(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return relative


def read(relative_path: str) -> bytes | None:
    path = _resolve(relative_path)
    return path.read_bytes() if path.is_file() else None


def delete(relative_path: str) -> None:
    _resolve(relative_path).unlink(missing_ok=True)
