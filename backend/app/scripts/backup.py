"""Back up the database and uploaded files (SEC-046).

    cd backend
    python -m app.scripts.backup --generate-key     # once; put it in BACKUP_ENCRYPTION_KEY
    python -m app.scripts.backup                    # back up, verify, delete old backups
    python -m app.scripts.backup --verify-only latest   # re-check an existing backup

Run it daily (see docs/BACKUPS.md). Exit code is non-zero if anything failed,
so a scheduler can alert on it.
"""

import argparse
import sys
from pathlib import Path

from app.config import settings
from app.services import backup


def latest(root: Path) -> Path:
    found = sorted(d for d in root.iterdir() if d.is_dir() and (d / "manifest.json").exists()) \
        if root.is_dir() else []
    if not found:
        raise backup.BackupError(f"No backups in {root}")
    return found[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Encrypted, verified backups of LaundryConnect")
    parser.add_argument("--generate-key", action="store_true", help="print a new encryption key and exit")
    parser.add_argument("--verify-only", metavar="FOLDER", help='check an existing backup ("latest" for the newest)')
    parser.add_argument("--no-verify", action="store_true", help="skip the test restore (not recommended)")
    parser.add_argument("--no-prune", action="store_true", help="keep old backups")
    args = parser.parse_args()
    root = Path(settings.backup_dir)

    if args.generate_key:
        print(backup.generate_key())
        print("Put this in backend/.env as BACKUP_ENCRYPTION_KEY=... and also store it in a "
              "password manager. Without it the backups can't be restored.", file=sys.stderr)
        return 0

    try:
        if args.verify_only:
            folder = latest(root) if args.verify_only == "latest" else Path(args.verify_only)
            result = backup.verify_backup(folder)
            print(f"OK  {folder.name}: restored {result['tables']} tables, {result['rows']} rows, "
                  f"{result['files']} files (schema {result['alembic_version']})")
            return 0

        made = backup.create_backup()
        m = made.manifest
        size = sum(f["size"] for f in m["files"].values())
        print(f"Backup {made.path.name}: {sum(m['table_counts'].values())} rows, "
              f"{m['upload_file_count']} files, {size / 1024 / 1024:.1f} MB encrypted")
        if not args.no_verify:
            result = backup.verify_backup(made.path)
            print(f"Verified: test restore reproduced {result['tables']} tables / "
                  f"{result['rows']} rows / {result['files']} files")
        if not args.no_prune:
            for old in backup.prune(root):
                print(f"Deleted old backup {old.name}")
        return 0
    except backup.BackupError as e:
        print(f"BACKUP FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
