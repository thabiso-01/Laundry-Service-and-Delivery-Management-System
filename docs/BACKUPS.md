# Backups and recovery (SEC-046, NFR-010)

Every backup contains the whole database and every uploaded file (ID documents,
photos). Backups are **encrypted**, **fingerprinted**, and **test-restored
automatically** each time one is made, so a broken backup is noticed the day it
happens, not the day you need it.

## 1. One-time setup

```bash
cd backend
python -m app.scripts.backup --generate-key
```

Put the printed key in `backend/.env`:

```
BACKUP_ENCRYPTION_KEY=...the key...
```

**Store the key in a password manager too.** Without it no backup can be
restored. Never store the key in the same place as the backups.

Optional settings (`backend/.env`):

| Setting | Default | Meaning |
|---|---|---|
| `BACKUP_DIR` | `backups` | Where backups are written |
| `BACKUP_KEEP_DAYS` | `30` | Delete backups older than this… |
| `BACKUP_MIN_KEEP` | `3` | …but always keep at least this many |
| `BACKUP_DOCKER_CONTAINER` | `laundryconnect-db` | Used when `pg_dump` isn't installed on the server |

## 2. Make a backup

```bash
cd backend
python -m app.scripts.backup
```

This:
1. dumps the database and packs the uploads folder, encrypting both as it goes;
2. writes `manifest.json` (time, schema version, row count per table, SHA-256 of each file);
3. **restores the backup into a temporary database** and checks every table's row count and every file against the manifest;
4. deletes backups older than `BACKUP_KEEP_DAYS` (keeping at least `BACKUP_MIN_KEEP`).

It prints `BACKUP FAILED: …` and exits with code 1 if anything goes wrong.

## 3. Run it every day

**Windows (Task Scheduler)** – from the `backend` folder, once:

```bat
schtasks /Create /SC DAILY /ST 02:00 /TN "LaundryConnect backup" ^
  /TR "cmd /c cd /d %CD% && .venv\Scripts\python.exe -m app.scripts.backup >> backups\backup.log 2>&1"
```

**Linux (cron)** – `crontab -e`:

```
0 2 * * * cd /srv/laundryconnect/backend && .venv/bin/python -m app.scripts.backup >> backups/backup.log 2>&1 || echo "LaundryConnect backup failed" | mail -s "Backup failed" ops@example.co.za
```

## 4. Keep a copy somewhere else

Backups on the same machine don't survive a disk failure, theft or ransomware.
Copy the `backups` folder off the server daily, e.g. with
[rclone](https://rclone.org) to cloud storage in South Africa (for POPIA,
prefer a South African region such as Azure South Africa North or AWS
af-south-1):

```bash
rclone sync backend/backups remote:laundryconnect-backups
```

The files are already encrypted, so the storage provider can't read them.

## 5. Restore

Check a backup without changing anything:

```bash
python -m app.scripts.backup --verify-only latest
```

Restore for real (**replaces the current database and uploads**):

1. Stop the API server.
2. Run:
   ```bash
   python -m app.scripts.restore latest --yes        # or: backups/20261115-020000
   ```
   It checks the fingerprints, does a test restore first, then replaces the
   database and puts the current uploads folder aside as
   `uploads.before-restore-<time>`.
3. Start the API server, log in and check a few recent orders.
4. Delete `uploads.before-restore-<time>` once you're satisfied.

## 6. Practise

Once a month, restore the latest backup on a spare machine or a copy of the
server and click through the app. The automatic test restore proves the files
are good; a practice run proves the *people* know what to do.

## What a backup does not cover

- The `.env` files and the encryption key – keep them in the password manager.
- Data written after the last backup (up to 24 hours with a daily schedule).
  For less loss, run backups more often or add PostgreSQL WAL archiving later.
