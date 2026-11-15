"""Test setup.

Tests use their own database (laundryconnect_test by default, or
TEST_DATABASE_URL), created and migrated automatically, so they never see or
touch your development data (e.g. the demo accounts). On top of that, every
test runs inside a transaction that is rolled back afterwards.
Run with:  cd backend  &&  pytest
"""

import os
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def _dev_database_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env_file = BACKEND / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return "postgresql+psycopg://laundry:laundry_dev_password@localhost:5432/laundryconnect"


def _prepare_test_database() -> None:
    """Point the app at the test database (before it's imported), create it
    if needed and bring it up to the latest migration."""
    from sqlalchemy import create_engine, text

    test_url = os.environ.get("TEST_DATABASE_URL") or (
        _dev_database_url().rsplit("/", 1)[0] + "/laundryconnect_test")
    os.environ["DATABASE_URL"] = test_url  # read by app.config.Settings

    server_url, db_name = test_url.rsplit("/", 1)
    admin = create_engine(f"{server_url}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db_name})
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin.dispose()

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")


_prepare_test_database()

from collections.abc import Callable, Iterator  # noqa: E402
from datetime import UTC, datetime  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings
from app.core.security import create_access_token, hash_password
from app.database import engine, get_db
from app.main import app
from app.models import (
    BusinessProfile,
    BusinessStaff,
    DriverProfile,
    LaundryService,
    User,
    VerificationDocument,
)
from app.models.enums import (
    BusinessStaffRole,
    PricingUnit,
    ServiceCategory,
    UserRole,
    VerificationStatus,
)
from app.services import documents

PASSWORD = "CorrectHorse42!"


@pytest.fixture(autouse=True)
def no_real_geocoding(monkeypatch):
    """Tests must never call the real geocoder (Nominatim) over the internet."""
    from app.services import geocode

    def _blocked(path, params):
        raise AssertionError("test tried to call the real geocoder")

    monkeypatch.setattr(geocode, "_fetch", _blocked)
    geocode.cache.clear()


@pytest.fixture(autouse=True)
def no_real_payfast(monkeypatch):
    """Tests must never call PayFast or resolve its servers over the internet."""
    from app.services import payfast

    def _blocked(*args, **kwargs):
        raise AssertionError("test tried to contact PayFast")

    monkeypatch.setattr(payfast, "_confirm_with_payfast", _blocked)
    monkeypatch.setattr(payfast, "_resolve_hosts", _blocked)


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    """Every test starts with empty per-IP counters."""
    from app.core.ratelimit import limiter
    limiter.reset()


@pytest.fixture(autouse=True)
def isolated_uploads(tmp_path, monkeypatch):
    """Uploaded files go to a throwaway folder, never backend/uploads."""
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    return tmp_path / "uploads"


@pytest.fixture
def approve_required_docs(db) -> Callable[[User], None]:
    """Give a driver / business owner approved records for every required
    document, so admin approval tests can focus on the approval itself."""

    def _approve(user: User) -> None:
        for req in documents.requirements_for(user):
            db.add(VerificationDocument(
                user_id=user.id, document_type=sorted(req.accepted)[0],
                file_path="n/a", original_filename="n/a", content_type="image/png",
                file_size=1, sha256="0" * 64, status=VerificationStatus.APPROVED,
            ))
        db.flush()

    return _approve


@pytest.fixture
def db() -> Iterator[Session]:
    conn = engine.connect()
    outer = conn.begin()
    # The app's own commit() calls only release a savepoint inside `outer`
    # expire_on_commit=False matches the app's SessionLocal, so tests catch
    # stale-data bugs the real app would have
    session = Session(bind=conn, join_transaction_mode="create_savepoint",
                      expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    """Insert a user directly (bypassing the API) for permission tests."""
    counter = iter(range(1, 10_000))

    def _make(role: UserRole, **kwargs) -> User:
        n = next(counter)
        user = User(
            email=kwargs.pop("email", f"{role.value}{n}@test.local"),
            password_hash=hash_password(PASSWORD),
            full_name=f"Test {role.value} {n}",
            role=role,
            # Like a normal self-registered user, who accepted the policy at sign-up
            privacy_consent_at=kwargs.pop("privacy_consent_at", datetime.now(UTC)),
            **kwargs,
        )
        db.add(user)
        db.flush()
        return user

    return _make


@pytest.fixture
def make_driver(make_user, db) -> Callable[..., User]:
    def _make(status: VerificationStatus = VerificationStatus.PENDING) -> User:
        user = make_user(UserRole.DRIVER)
        user.driver_profile = DriverProfile(
            id_number=f"P{user.id.hex[:10].upper()}", verification_status=status
        )
        db.flush()
        return user

    return _make


@pytest.fixture
def make_business(make_user, db) -> Callable[..., BusinessProfile]:
    def _make(status: VerificationStatus = VerificationStatus.APPROVED) -> BusinessProfile:
        owner = make_user(UserRole.BUSINESS)
        biz = BusinessProfile(owner=owner, business_name="Test Laundry", verification_status=status)
        biz.staff.append(BusinessStaff(user=owner, staff_role=BusinessStaffRole.OWNER))
        db.add(biz)
        db.flush()
        return biz

    return _make


@pytest.fixture
def make_laundry(make_business, db) -> Callable[..., BusinessProfile]:
    """An approved, mapped business with services: ready to take orders.
    services: list of (name, category, unit, price_cents, turnaround_hours[, min_qty])."""

    def _make(lat: float = -26.1929, lng: float = 28.0305, services=None) -> BusinessProfile:
        biz = make_business(VerificationStatus.APPROVED)
        biz.business_name = "Braam Laundry"
        biz.latitude, biz.longitude = lat, lng
        for spec in services or [("Wash & Fold", "wash_and_fold", "per_kg", 2500, 48, 3)]:
            name, category, unit, price, hours, *rest = spec
            db.add(LaundryService(
                business=biz, name=name, category=ServiceCategory(category),
                pricing_unit=PricingUnit(unit), price_cents=price, turnaround_hours=hours,
                min_quantity=rest[0] if rest else 1,
            ))
        db.flush()
        return biz

    return _make


@pytest.fixture
def add_staff(make_user, db) -> Callable[..., User]:
    def _add(business: BusinessProfile, role: BusinessStaffRole, active: bool = True) -> User:
        user = make_user(UserRole.BUSINESS)
        db.add(BusinessStaff(business=business, user=user, staff_role=role, is_active=active))
        db.flush()
        return user

    return _add


def pay(client, customer: User, order: dict) -> None:
    """Pay what's owed on an order through the sandbox gateway."""
    h = auth_header(customer)
    checkout = client.post(f"/api/orders/{order['id']}/pay", headers=h)
    assert checkout.status_code == 200, checkout.text
    done = client.post(f"/api/payments/sandbox/{checkout.json()['reference']}/complete",
                       headers=h, json={"outcome": "paid"})
    assert done.json()["outcome"] == "applied", done.text


def auth_header(user: User) -> dict[str, str]:
    token, _ = create_access_token(user.id, user.role.value)
    return {"Authorization": f"Bearer {token}"}
