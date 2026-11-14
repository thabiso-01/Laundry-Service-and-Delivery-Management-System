"""Business profile editing and service catalog (UR-003, UR-006, Business Rules 8 & 11)."""

import pytest
from sqlalchemy import select

from app.models import AuditLog, LaundryService
from app.models.enums import BusinessStaffRole as S
from app.models.enums import UserRole
from app.models.enums import VerificationStatus as V
from tests.conftest import auth_header

WASH = {
    "name": "Wash & Fold",
    "category": "wash_and_fold",
    "pricing_unit": "per_kg",
    "price_cents": 2500,
    "min_quantity": 3,
    "turnaround_hours": 48,
}


@pytest.fixture
def biz(make_business):
    return make_business(V.APPROVED)


def create(client, user, **overrides):
    return client.post("/api/business/services", headers=auth_header(user), json=WASH | overrides)


# ---------- Profile ----------

def test_staff_can_view_profile(client, biz, add_staff):
    attendant = add_staff(biz, S.ATTENDANT)
    r = client.get("/api/business/profile", headers=auth_header(attendant))
    assert r.status_code == 200
    assert r.json()["id"] == str(biz.id)


def test_manager_updates_profile_and_change_is_audited(client, biz, add_staff, db):
    manager = add_staff(biz, S.MANAGER)
    r = client.patch("/api/business/profile", headers=auth_header(manager), json={
        "description": "Same-day service in Soweto",
        "contact_phone": "011 123 4567",
        "latitude": -26.25, "longitude": 27.85,
    })
    assert r.status_code == 200, r.text
    assert r.json()["contact_phone"] == "+27111234567"
    assert r.json()["latitude"] == -26.25

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "business.profile_updated"))
    assert entry.actor_user_id == manager.id
    assert entry.details["description"] == {"from": None, "to": "Same-day service in Soweto"}


def test_attendant_cannot_update_profile(client, biz, add_staff):
    attendant = add_staff(biz, S.ATTENDANT)
    r = client.patch("/api/business/profile", headers=auth_header(attendant),
                     json={"description": "x"})
    assert r.status_code == 403


def test_registration_number_cannot_be_changed(client, biz):
    r = client.patch("/api/business/profile", headers=auth_header(biz.owner),
                     json={"registration_number": "9999/999999/07"})
    assert r.status_code == 422


def test_coordinates_must_be_sent_together(client, biz):
    r = client.patch("/api/business/profile", headers=auth_header(biz.owner),
                     json={"latitude": -26.2})
    assert r.status_code == 422


# ---------- Services ----------

def test_manager_creates_service(client, biz, add_staff, db):
    manager = add_staff(biz, S.MANAGER)
    r = create(client, manager)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["price_cents"] == 2500
    assert body["price_display"] == "R25.00 per kg"
    assert body["is_active"] is True

    entry = db.scalar(select(AuditLog).where(AuditLog.action == "service.created"))
    assert entry.details["price_cents"] == 2500


def test_price_display_uses_sa_format(client, biz):
    r = create(client, biz.owner, name="Wedding dress", category="speciality",
               pricing_unit="per_item", price_cents=125050, min_quantity=1)
    assert r.json()["price_display"] == "R1 250.50 per item"


def test_pending_business_can_prepare_catalog(client, make_business):
    pending = make_business(V.PENDING)
    assert create(client, pending.owner).status_code == 201


def test_attendant_can_view_but_not_change_services(client, biz, add_staff):
    attendant = add_staff(biz, S.ATTENDANT)
    create(client, biz.owner)
    assert create(client, attendant, name="Ironing").status_code == 403
    r = client.get("/api/business/services", headers=auth_header(attendant))
    assert r.status_code == 200
    assert [s["name"] for s in r.json()] == ["Wash & Fold"]


@pytest.mark.parametrize("bad", [
    {"price_cents": 0},
    {"price_cents": -100},
    {"price_cents": 2_000_000},  # R20 000 – almost certainly a typo
    {"turnaround_hours": 0},
    {"pricing_unit": "per_hour"},
    {"name": "x"},
    {"business_id": "00000000-0000-0000-0000-000000000000"},  # can't target another business
])
def test_invalid_service_rejected(client, biz, bad):
    assert create(client, biz.owner, **bad).status_code == 422


def test_duplicate_service_name_rejected(client, biz):
    assert create(client, biz.owner).status_code == 201
    assert create(client, biz.owner).status_code == 409


def test_price_change_is_audited_with_old_and_new(client, biz, db):
    service_id = create(client, biz.owner).json()["id"]
    r = client.patch(f"/api/business/services/{service_id}", headers=auth_header(biz.owner),
                     json={"price_cents": 2800})
    assert r.status_code == 200
    assert r.json()["price_cents"] == 2800
    entry = db.scalar(select(AuditLog).where(AuditLog.action == "service.updated"))
    assert entry.details == {"price_cents": {"from": 2500, "to": 2800}}


def test_update_with_no_real_change_is_not_audited(client, biz, db):
    service_id = create(client, biz.owner).json()["id"]
    client.patch(f"/api/business/services/{service_id}", headers=auth_header(biz.owner),
                 json={"price_cents": 2500})
    assert db.scalar(select(AuditLog).where(AuditLog.action == "service.updated")) is None


def test_cannot_null_out_required_fields(client, biz):
    service_id = create(client, biz.owner).json()["id"]
    r = client.patch(f"/api/business/services/{service_id}", headers=auth_header(biz.owner),
                     json={"price_cents": None})
    assert r.status_code == 422


def test_deactivate_hides_service_but_keeps_it(client, biz, db):
    service_id = create(client, biz.owner).json()["id"]
    h = auth_header(biz.owner)
    assert client.delete(f"/api/business/services/{service_id}", headers=h).status_code == 204

    assert client.get("/api/business/services", headers=h).json() == []
    everything = client.get("/api/business/services?include_inactive=true", headers=h).json()
    assert everything[0]["is_active"] is False
    assert db.get(LaundryService, service_id) is not None

    r = client.patch(f"/api/business/services/{service_id}", headers=h, json={"is_active": True})
    assert r.json()["is_active"] is True


# ---------- Isolation between businesses (Business Rule 8) ----------

def test_cannot_touch_another_businesses_services(client, biz, make_business):
    other = make_business(V.APPROVED)
    service_id = create(client, other.owner).json()["id"]
    h = auth_header(biz.owner)

    assert client.patch(f"/api/business/services/{service_id}", headers=h,
                        json={"price_cents": 1}).status_code == 404
    assert client.delete(f"/api/business/services/{service_id}", headers=h).status_code == 404
    assert client.get("/api/business/services", headers=h).json() == []


def test_same_service_name_allowed_at_different_businesses(client, biz, make_business):
    other = make_business(V.APPROVED)
    assert create(client, biz.owner).status_code == 201
    assert create(client, other.owner).status_code == 201


@pytest.mark.parametrize("role", [UserRole.CUSTOMER, UserRole.DRIVER, UserRole.ADMIN])
def test_non_business_users_blocked(client, make_user, role):
    user = make_user(role)
    assert client.get("/api/business/services", headers=auth_header(user)).status_code == 403
    assert create(client, user).status_code == 403


def test_deactivated_staff_blocked(client, biz, add_staff):
    former = add_staff(biz, S.MANAGER, active=False)
    assert create(client, former).status_code == 403
