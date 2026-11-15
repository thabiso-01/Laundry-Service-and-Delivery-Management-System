"""Encrypted backups of the database and uploaded files, and verified restores (SEC-046).

A backup is a folder  backups/<YYYYmmdd-HHMMSS>/  containing
    database.dump.enc   pg_dump custom format, encrypted
    uploads.tar.gz.enc  every uploaded file (ID documents, photos), encrypted
    manifest.json       when, schema version, row counts, SHA-256 of each file

Encryption: the data is cut into chunks, each sealed with Fernet (AES-128-CBC +
HMAC-SHA256), so any change to a backup file is detected and large upload
folders never need to fit in memory. The key lives outside the backups.

pg_dump/pg_restore run on the host when installed, otherwise inside the
database's Docker container.
"""

import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import tarfile
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url

from app.config import settings

MAGIC = b"LCBACKUP1\n"
CHUNK = 8 * 1024 * 1024
FORMAT_VERSION = 1


class BackupError(Exception):
    pass


# ---------- Encryption (chunked Fernet) ----------

def generate_key() -> str:
    return Fernet.generate_key().decode()


def _fernet(key: str | None = None) -> Fernet:
    key = key or settings.backup_encryption_key
    if not key:
        raise BackupError("BACKUP_ENCRYPTION_KEY is not set. Create one with "
                          "`python -m app.scripts.backup --generate-key` and keep it safe.")
    try:
        return Fernet(key.encode())
    except ValueError as e:
        raise BackupError("BACKUP_ENCRYPTION_KEY is not a valid key") from e


class EncryptedWriter(io.RawIOBase):
    """File-like object: bytes written to it are encrypted in chunks."""

    def __init__(self, out: BinaryIO, fernet: Fernet, chunk_size: int = CHUNK):
        self.out, self.fernet, self.chunk_size = out, fernet, chunk_size
        self.buffer = bytearray()
        out.write(MAGIC)

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:  # type: ignore[override]
        self.buffer += data
        while len(self.buffer) >= self.chunk_size:
            self._seal(bytes(self.buffer[:self.chunk_size]))
            del self.buffer[:self.chunk_size]
        return len(data)

    def _seal(self, plain: bytes) -> None:
        token = self.fernet.encrypt(plain)
        self.out.write(struct.pack(">I", len(token)) + token)

    def close(self) -> None:
        if not self.closed:
            if self.buffer:
                self._seal(bytes(self.buffer))
            self.out.write(struct.pack(">I", 0))  # end marker: detects truncated files
            super().close()


def decrypted_chunks(src: BinaryIO, fernet: Fernet) -> Iterator[bytes]:
    if src.read(len(MAGIC)) != MAGIC:
        raise BackupError("Not a LaundryConnect backup file")
    while True:
        header = src.read(4)
        if len(header) < 4:
            raise BackupError("Backup file is truncated")
        (size,) = struct.unpack(">I", header)
        if size == 0:
            return
        token = src.read(size)
        if len(token) < size:
            raise BackupError("Backup file is truncated")
        try:
            yield fernet.decrypt(token)
        except InvalidToken as e:
            raise BackupError("Backup file was altered, or the encryption key is wrong") from e


class DecryptedReader(io.RawIOBase):
    """File-like object that decrypts as it's read (for streaming tar extraction)."""

    def __init__(self, src: BinaryIO, fernet: Fernet):
        self.chunks = decrypted_chunks(src, fernet)
        self.pending = b""

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:  # type: ignore[override]
        while not self.pending:
            try:
                self.pending = next(self.chunks)
            except StopIteration:
                return 0
        n = min(len(b), len(self.pending))
        b[:n] = self.pending[:n]
        self.pending = self.pending[n:]
        return n


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


# ---------- Running pg_dump / pg_restore ----------

def _db_url(url: str | None = None) -> URL:
    return make_url(url or settings.database_url)


def _pg_command(tool: str, url: URL, args: list[str], interactive: bool = False) -> tuple[list[str], dict]:
    """Host tool if installed, else `docker exec` into the database container."""
    env = dict(os.environ)
    if shutil.which(tool):
        if url.password:
            env["PGPASSWORD"] = url.password
        return [tool, "-h", url.host or "localhost", "-p", str(url.port or 5432),
                "-U", url.username or "postgres", *args], env
    if not shutil.which("docker"):
        raise BackupError(f"Neither {tool} nor docker is available")
    exec_args = ["docker", "exec"] + (["-i"] if interactive else [])
    return [*exec_args, settings.backup_docker_container, tool,
            "-U", url.username or "postgres", *args], env


def _connect_admin(url: URL):
    return create_engine(url.set(drivername="postgresql+psycopg", database="postgres"),
                         isolation_level="AUTOCOMMIT")


def snapshot(url: URL) -> dict[str, Any]:
    """Schema version and row count of every table – what a restore must reproduce."""
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            tables = sorted(t for t in inspect(conn).get_table_names() if t != "alembic_version")
            counts = {t: conn.scalar(text(f'SELECT count(*) FROM "{t}"')) for t in tables}
            version = conn.scalar(text("SELECT version_num FROM alembic_version"))
        return {"alembic_version": version, "table_counts": counts}
    finally:
        engine.dispose()


# ---------- Create ----------

@dataclass
class BackupResult:
    path: Path
    manifest: dict[str, Any]


def create_backup(backup_root: Path | None = None, uploads_dir: Path | None = None,
                  database_url: str | None = None, key: str | None = None) -> BackupResult:
    fernet = _fernet(key)
    url = _db_url(database_url)
    root = Path(backup_root or settings.backup_dir)
    uploads = Path(uploads_dir or settings.upload_dir)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    folder = root / stamp
    folder.mkdir(parents=True, exist_ok=False)

    try:
        state = snapshot(url)

        # 1. Database, streamed straight from pg_dump into the encrypter
        cmd, env = _pg_command("pg_dump", url, ["-Fc", "--no-owner", "-d", url.database])
        db_file = folder / "database.dump.enc"
        with db_file.open("wb") as out:
            writer = EncryptedWriter(out, fernet)
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
            assert proc.stdout is not None
            for block in iter(lambda: proc.stdout.read(1024 * 1024), b""):
                writer.write(block)
            stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            if proc.wait() != 0:
                raise BackupError(f"pg_dump failed: {stderr.strip()[:500]}")
            writer.close()

        # 2. Uploaded files, as a streamed tar.gz
        up_file = folder / "uploads.tar.gz.enc"
        file_count = 0
        with up_file.open("wb") as out:
            writer = EncryptedWriter(out, fernet)
            with tarfile.open(fileobj=writer, mode="w|gz") as tar:
                if uploads.is_dir():
                    for path in sorted(p for p in uploads.rglob("*") if p.is_file()):
                        tar.add(path, arcname=path.relative_to(uploads).as_posix())
                        file_count += 1
            writer.close()

        manifest = {
            "format_version": FORMAT_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "database": url.database,
            **state,
            "upload_file_count": file_count,
            "files": {f.name: {"size": f.stat().st_size, "sha256": sha256_file(f)}
                      for f in (db_file, up_file)},
            "encrypted": True,
        }
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return BackupResult(folder, manifest)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)  # never leave a half-written backup
        raise


# ---------- Check integrity, restore ----------

def load_manifest(folder: Path) -> dict[str, Any]:
    path = folder / "manifest.json"
    if not path.is_file():
        raise BackupError(f"{folder} has no manifest.json – not a complete backup")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for name, info in manifest["files"].items():
        f = folder / name
        if not f.is_file():
            raise BackupError(f"{name} is missing from the backup")
        if sha256_file(f) != info["sha256"]:
            raise BackupError(f"{name} doesn't match its fingerprint – the backup was damaged or altered")
    return manifest


def restore_database(folder: Path, target_url: URL, key: str | None = None) -> None:
    """Restores into an existing, empty database."""
    fernet = _fernet(key)
    cmd, env = _pg_command("pg_restore", target_url,
                           ["--no-owner", "--exit-on-error", "-d", target_url.database],
                           interactive=True)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env)
    assert proc.stdin is not None
    try:
        with (folder / "database.dump.enc").open("rb") as src:
            for chunk in decrypted_chunks(src, fernet):
                proc.stdin.write(chunk)
        proc.stdin.close()
    except BaseException:
        proc.kill()
        raise
    stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
    if proc.wait() != 0:
        raise BackupError(f"pg_restore failed: {stderr.strip()[:500]}")


def restore_uploads(folder: Path, target_dir: Path, key: str | None = None) -> int:
    fernet = _fernet(key)
    target_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    with (folder / "uploads.tar.gz.enc").open("rb") as src:
        with tarfile.open(fileobj=DecryptedReader(src, fernet), mode="r|gz") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                # Refuse anything that would escape the target folder
                dest = (target_dir / member.name).resolve()
                if not dest.is_relative_to(target_dir.resolve()):
                    raise BackupError(f"Unsafe path in backup: {member.name}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as data, dest.open("wb") as out:  # type: ignore[union-attr]
                    shutil.copyfileobj(data, out)
                count += 1
    return count


def _create_database(url: URL, name: str) -> None:
    admin = _connect_admin(url)
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()


def _drop_database(url: URL, name: str) -> None:
    admin = _connect_admin(url)
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


def verify_backup(folder: Path, database_url: str | None = None, key: str | None = None,
                  scratch_dir: Path | None = None) -> dict[str, Any]:
    """Proves the backup can be restored: restores it into a throwaway database
    and folder, compares with the manifest, then removes them."""
    manifest = load_manifest(folder)
    url = _db_url(database_url)
    temp_name = f"laundryconnect_restore_check_{uuid.uuid4().hex[:8]}"
    temp_url = url.set(database=temp_name)
    _create_database(url, temp_name)
    try:
        restore_database(folder, temp_url, key)
        restored = snapshot(temp_url)
    finally:
        _drop_database(url, temp_name)
    if restored["alembic_version"] != manifest["alembic_version"]:
        raise BackupError("Restored schema version doesn't match the backup")
    if restored["table_counts"] != manifest["table_counts"]:
        diff = {t: (manifest["table_counts"].get(t), restored["table_counts"].get(t))
                for t in set(manifest["table_counts"]) | set(restored["table_counts"])
                if manifest["table_counts"].get(t) != restored["table_counts"].get(t)}
        raise BackupError(f"Restored row counts differ from the backup: {diff}")

    scratch = Path(scratch_dir or (folder / ".verify-uploads"))
    try:
        files = restore_uploads(folder, scratch, key)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if files != manifest["upload_file_count"]:
        raise BackupError(f"Expected {manifest['upload_file_count']} uploaded files, restored {files}")
    return {"tables": len(restored["table_counts"]),
            "rows": sum(restored["table_counts"].values()),
            "files": files, "alembic_version": restored["alembic_version"]}


# ---------- Retention ----------

def prune(backup_root: Path | None = None, keep_days: int | None = None,
          min_keep: int | None = None, now: datetime | None = None) -> list[Path]:
    """Deletes backups older than keep_days, always keeping the newest min_keep."""
    root = Path(backup_root or settings.backup_dir)
    keep_days = settings.backup_keep_days if keep_days is None else keep_days
    min_keep = settings.backup_min_keep if min_keep is None else min_keep
    now = now or datetime.now(UTC)
    backups = []
    for d in root.iterdir() if root.is_dir() else []:
        try:
            when = datetime.strptime(d.name, "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            continue  # not one of ours
        if d.is_dir():
            backups.append((when, d))
    backups.sort(reverse=True)
    removed = []
    for when, d in backups[min_keep:]:
        if now - when > timedelta(days=keep_days):
            shutil.rmtree(d)
            removed.append(d)
    return removed
