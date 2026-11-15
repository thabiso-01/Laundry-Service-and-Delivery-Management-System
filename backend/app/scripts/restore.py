"""Restore LaundryConnect from a backup (SEC-046). REPLACES the current data.

    cd backend
    python -m app.scripts.restore latest --yes
    python -m app.scripts.restore backups/20261115-020000 --yes

Stop the API server first. The current database is replaced; the current
uploads folder is kept aside as uploads.before-restore-<time> (delete it once
you're happy). Use `python -m app.scripts.backup --verify-only <folder>` to
test a backup without touching anything.
"""

import argparse
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.config import settings
from app.scripts.backup import latest
from app.services import backup


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore LaundryConnect from a backup")
    parser.add_argument("folder", help='backup folder, or "latest"')
    parser.add_argument("--yes", action="store_true", help="confirm: replace the current data")
    args = parser.parse_args()

    try:
        folder = latest(Path(settings.backup_dir)) if args.folder == "latest" else Path(args.folder)
        manifest = backup.load_manifest(folder)  # fingerprints checked before anything changes
        url = backup._db_url()
        print(f"Backup {folder.name} from {manifest['created_at']}: "
              f"{sum(manifest['table_counts'].values())} rows, {manifest['upload_file_count']} files")
        if not args.yes:
            print(f"Nothing changed. Re-run with --yes to REPLACE database '{url.database}' "
                  f"and the uploads folder.")
            return 1

        # Prove the backup restores cleanly before destroying anything
        backup.verify_backup(folder)

        backup._drop_database(url, url.database)
        backup._create_database(url, url.database)
        backup.restore_database(folder, url)
        print(f"Database '{url.database}' restored.")

        uploads = Path(settings.upload_dir)
        if uploads.exists():
            aside = uploads.with_name(f"{uploads.name}.before-restore-{datetime.now(UTC):%Y%m%d-%H%M%S}")
            shutil.move(str(uploads), str(aside))
            print(f"Previous uploads kept in {aside}")
        files = backup.restore_uploads(folder, uploads)
        print(f"{files} uploaded files restored. Start the API server again.")
        return 0
    except backup.BackupError as e:
        print(f"RESTORE FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
