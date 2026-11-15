# LaundryConnect – Laundry Service and Delivery Management System

Application that helps users request laundry collection and delivery, connecting
customers, laundry businesses and delivery drivers.

## Stack

| Part      | Technology                                  |
|-----------|---------------------------------------------|
| Backend   | Python, FastAPI, SQLAlchemy, Alembic         |
| Frontend  | React, TypeScript, Vite, Tailwind CSS        |
| Database  | PostgreSQL 16 (runs in Docker)               |

## Project layout

```
backend/            FastAPI API  (http://localhost:8000, docs at /docs)
frontend/           React web app (http://localhost:5173)
docker-compose.yml  PostgreSQL database
```

## Getting started

**1. Environment files** (first time only)

```bash
cp .env.example .env
cp backend/.env.example backend/.env
```

**2. Database** – start Docker Desktop, then:

```bash
docker compose up -d
```

**3. Backend**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
alembic upgrade head            # create / update database tables
uvicorn app.main:app --reload
```

In `backend/.env`, set `JWT_SECRET_KEY` to your own random value – the API won't
start without it:
`python -c "import secrets; print(secrets.token_urlsafe(48))"`

**Create an administrator** (admins can't sign up through the API):

```bash
python -m app.scripts.create_admin --email admin@example.co.za --name "Your Name"
```

**Run the tests.** They use a separate `laundryconnect_test` database, created and
migrated automatically, so your development data (e.g. demo accounts) is never
touched. Tests never call the real address-search service.

```bash
pytest
```

> No working `python` on your PATH? With [uv](https://docs.astral.sh/uv/) installed,
> `uv venv --python 3.12 .venv` creates the environment instead of `python -m venv`.

### Changing the database

Edit the models in `backend/app/models/`, then:

```bash
alembic revision --autogenerate -m "describe the change"   # review the generated file!
alembic upgrade head
```

**4. Frontend** (in a second terminal)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

> On Windows, `uvicorn --reload` sometimes stops picking up changes. If new
> endpoints don't appear, stop the server and start it again without `--reload`.

## Try it with demo accounts

```bash
cd backend
python -m app.scripts.seed_demo --yes
```

All demo accounts use the password **`DemoPass#2026`** (development only):

| Log in as | Email | What to try |
|---|---|---|
| Customer | `customer@demo.lc` | Find a laundry → choose services → see price → place order → pay (sandbox) → show the collection code to the driver |
| Laundry owner | `owner@demo.lc` | Accept the paid order → after collection, receive the bag (copy the code under the QR label + seal numbers) → weigh → processing → ready |
| Laundry attendant | `attendant@demo.lc` | Same order queue, no access to staff or prices |
| Driver | `driver1@demo.lc`, `driver2@demo.lc` | Go online → accept a job → collect with the customer's code and a seal number (any 4–20 letters/digits) → … |
| Admin | `admin@demo.lc` | Verification queues, incidents with evidence, route alerts |

Tip: use two browser profiles (or a private window) to be logged in as two people at once.

## Screens

| Role | Screens |
|---|---|
| Everyone | Log in (incl. two-step), register, change password, notifications, my reports, account security (MFA) |
| Customer | Search & compare → laundry page & checkout → order page (pay, one-time code, live driver, handovers, seals, cancel, review, report) |
| Laundry | Order queue & dashboard → order page (accept/decline, receive by QR + seals, weigh, processing → ready, QR label) · services & prices · staff · profile · documents |
| Driver | Online/offline, job board, my jobs → job page (collect / pick up / deliver, live location sharing) · documents · ratings |
| Admin | Driver & laundry verification with document review · incidents & investigation · route deviations |

**Scanning bag labels.** Laundry staff and drivers scan QR labels with the
camera (or by taking a photo; typing the code still works). Browsers only allow
the camera on `https` or `localhost`, so to try it on a phone:

```bash
cd frontend
npm run dev:phone     # https on your network, e.g. https://192.168.1.20:5173
```

Open the address it prints on your phone (same Wi-Fi) and accept the
self-signed certificate warning once.

**Maps and address search.** Addresses are found with OpenStreetMap
(Nominatim), called through the backend at `/api/geocode` – limited to South
Africa, one request per second, cached, and rate-limited per user. Maps use
Leaflet with OpenStreetMap tiles. Both are free and need no API key, but their
usage policies only allow light traffic: before launch, set
`GEOCODER_USER_AGENT` to include your contact e-mail, and move to a paid or
self-hosted geocoder and tile provider for real volumes. Mention in the privacy
policy that searched addresses are sent to OpenStreetMap (POPIA).

**POPIA rights.** Under *Account & privacy* every user can download all their
data as JSON (`GET /api/me/data-export`, s23) and delete their account
(`DELETE /api/me`, s24). Deletion wipes personal details, ID documents,
notifications, review comments and location history. Records the law requires
are kept but stripped of identifying details: orders and payments (amounts,
dates and suburb, for SARS, 5 years), handover/seal/photo evidence, reports and
the security log. Deletion is refused while an order or delivery job is in
progress, and laundry owners must hand over or close the business first. The
privacy policy should state these retention periods.

**Rate limits.** Login, registration, password changes, reports, photo uploads
and address search are limited per IP address (429 + `Retry-After` when
exceeded; the first block per window is audited). Limits are in
`backend/app/config.py` (`RATELIMIT_*` settings). Behind a reverse proxy or load
balancer, start the API with
`uvicorn app.main:app --proxy-headers --forwarded-allow-ips=<proxy IP>` so the
real visitor IP is used — otherwise every visitor looks like the proxy. Counts
are kept in memory; with several API processes, move them to Redis.

**Backups.** `python -m app.scripts.backup` makes an encrypted backup of the
database and uploaded files and test-restores it automatically. Set it up to run
daily and copy it off the server: see [docs/BACKUPS.md](docs/BACKUPS.md).

## End-to-end tests

With the backend and `npm run dev` running and the demo accounts seeded:

```bash
cd frontend
npm run e2e        # drives the installed Chrome; screenshots in e2e/screenshots/
```
