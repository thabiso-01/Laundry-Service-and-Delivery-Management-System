"""Encrypted backups and verified restores (SEC-046)."""

import io
import json
import shutil
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.services import backup

KEY = Fernet.generate_key().decode()


def encrypt(data: bytes, key: str = KEY, chunk: int = 10) -> bytes:
    out = io.BytesIO()
    w = backup.EncryptedWriter(out, Fernet(key.encode()), chunk_size=chunk)
    w.write(data)
    w.close()
    return out.getvalue()


def decrypt(blob: bytes, key: str = KEY) -> bytes:
    return b"".join(backup.decrypted_chunks(io.BytesIO(blob), Fernet(key.encode())))


# ---------- Encryption ----------

def test_round_trip_across_many_chunks():
    data = bytes(range(256)) * 7
    blob = encrypt(data, chunk=100)
    assert data not in blob
    assert decrypt(blob) == data


def test_wrong_key_is_refused():
    with pytest.raises(backup.BackupError, match="altered, or the encryption key is wrong"):
        decrypt(encrypt(b"secret ID numbers"), key=Fernet.generate_key().decode())


def test_tampering_is_detected():
    blob = bytearray(encrypt(b"x" * 50))
    blob[len(backup.MAGIC) + 20] ^= 0x01
    with pytest.raises(backup.BackupError):
        decrypt(bytes(blob))


def test_truncated_file_is_detected():
    blob = encrypt(b"y" * 50)
    with pytest.raises(backup.BackupError, match="truncated"):
        decrypt(blob[:-4])  # end marker cut off


def test_missing_key_explains_what_to_do(monkeypatch):
    monkeypatch.setattr(backup.settings, "backup_encryption_key", "")
    with pytest.raises(backup.BackupError, match="--generate-key"):
        backup._fernet()


# ---------- Retention ----------

def test_prune_keeps_recent_and_minimum(tmp_path):
    now = datetime(2026, 11, 15, 2, 0, tzinfo=UTC)
    for days in (0, 1, 40, 50, 60):
        (tmp_path / (now - timedelta(days=days)).strftime("%Y%m%d-%H%M%S")).mkdir()
    (tmp_path / "not-a-backup").mkdir()

    removed = backup.prune(tmp_path, keep_days=30, min_keep=3, now=now)
    # 60 and 50 days old go; the 40-day-old one stays because it's the 3rd newest
    assert sorted(p.name for p in removed) == ["20260916-020000", "20260926-020000"]
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["20261006-020000", "20261114-020000", "20261115-020000", "not-a-backup"]


def test_prune_never_empties_the_folder(tmp_path):
    now = datetime(2026, 11, 15, tzinfo=UTC)
    for days in (100, 200):
        (tmp_path / (now - timedelta(days=days)).strftime("%Y%m%d-%H%M%S")).mkdir()
    assert backup.prune(tmp_path, keep_days=30, min_keep=3, now=now) == []


# ---------- Real backup and restore (test database) ----------

tools = shutil.which("pg_dump") or shutil.which("docker")
needs_postgres_tools = pytest.mark.skipif(not tools, reason="needs pg_dump or docker")


@pytest.fixture
def uploads(tmp_path):
    d = tmp_path / "uploads"
    (d / "user-1").mkdir(parents=True)
    (d / "user-1" / "id.pdf").write_bytes(b"%PDF-1.7 pretend ID document")
    (d / "photos" / "order-1").mkdir(parents=True)
    (d / "photos" / "order-1" / "bag.png").write_bytes(b"\x89PNG pretend photo")
    return d


@needs_postgres_tools
def test_backup_verify_and_restore_files(tmp_path, uploads):
    made = backup.create_backup(tmp_path / "backups", uploads, key=KEY)
    m = made.manifest
    assert m["encrypted"] is True and m["upload_file_count"] == 2
    assert m["alembic_version"]
    assert "orders" in m["table_counts"] and "users" in m["table_counts"]
    for name in ("database.dump.enc", "uploads.tar.gz.enc", "manifest.json"):
        assert (made.path / name).is_file()
    # The ID document's contents aren't readable in the backup
    assert b"pretend ID document" not in (made.path / "uploads.tar.gz.enc").read_bytes()

    result = backup.verify_backup(made.path, key=KEY, scratch_dir=tmp_path / "scratch")
    assert result["files"] == 2 and result["tables"] == len(m["table_counts"])

    restored = tmp_path / "restored"
    assert backup.restore_uploads(made.path, restored, key=KEY) == 2
    assert (restored / "user-1" / "id.pdf").read_bytes() == b"%PDF-1.7 pretend ID document"


@needs_postgres_tools
def test_damaged_backup_is_refused(tmp_path, uploads):
    made = backup.create_backup(tmp_path / "backups", uploads, key=KEY)
    dump = made.path / "database.dump.enc"
    data = bytearray(dump.read_bytes())
    data[len(data) // 2] ^= 0xFF
    dump.write_bytes(bytes(data))
    with pytest.raises(backup.BackupError, match="fingerprint"):
        backup.verify_backup(made.path, key=KEY)


@needs_postgres_tools
def test_failed_backup_leaves_nothing_behind(tmp_path, uploads, monkeypatch):
    monkeypatch.setattr(backup, "_pg_command",
                        lambda *a, **k: (["python", "-c", "import sys; sys.exit(3)"], {}))
    with pytest.raises(backup.BackupError, match="pg_dump failed"):
        backup.create_backup(tmp_path / "backups", uploads, key=KEY)
    assert list((tmp_path / "backups").iterdir()) == []


def test_restore_refuses_paths_outside_the_folder(tmp_path):
    """A malicious backup can't write files outside the uploads folder."""
    folder = tmp_path / "evil"
    folder.mkdir()
    with (folder / "uploads.tar.gz.enc").open("wb") as out:
        w = backup.EncryptedWriter(out, Fernet(KEY.encode()))
        with tarfile.open(fileobj=w, mode="w|gz") as tar:
            info = tarfile.TarInfo("../../outside.txt")
            payload = b"gotcha"
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        w.close()
    with pytest.raises(backup.BackupError, match="Unsafe path"):
        backup.restore_uploads(folder, tmp_path / "target", key=KEY)
    assert not (tmp_path / "outside.txt").exists()


def test_manifest_required(tmp_path):
    with pytest.raises(backup.BackupError, match="manifest"):
        backup.load_manifest(tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({"files": {"database.dump.enc": {"sha256": "x"}}}))
    with pytest.raises(backup.BackupError, match="missing"):
        backup.load_manifest(tmp_path)
