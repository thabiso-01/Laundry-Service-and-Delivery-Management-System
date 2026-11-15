#!/bin/sh
# Bring the database schema up to date, then start the API.
set -e

echo "Applying database migrations..."
alembic upgrade head

# One process: per-IP rate limits and the SMS worker live in memory.
# --proxy-headers: trust Caddy (the only thing that can reach this container)
# to pass on the real visitor IP, so rate limits and audit logs see it.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  --proxy-headers --forwarded-allow-ips="*" --no-server-header
