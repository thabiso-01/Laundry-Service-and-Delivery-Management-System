"""Nearby laundry search and comparison (UR-005, UR-006, UAT-002, UAT-003)."""

import pytest

from app.models import LaundryService
from app.models.enums import AccountStatus, PricingUnit, ServiceCategory
from app.models.enums import VerificationStatus as V
from app.services.search import haversine_km

# Searcher stands in Johannesburg CBD
JHB = (-26.2041, 28.0473)
PLACES = {
    "Braamfontein": (-26.1929, 28.0305),  # ~2 km
    "Sandton": (-26.1076, 28.0567),       # ~11 km
    "Soweto": (-26.2485, 27.8540),        # ~20 km
    "Pretoria": (-25.7479, 28.2293),      # ~54 km
}


@pytest.fixture
def place(make_business, db):
    """Create a bookable business at a named location with services."""

    def _place(where, name=None, *, status=V.APPROVED, services=None):
        biz = make_business(status)
        biz.business_name = name or f"{where} Laundry"
        biz.suburb = where
        biz.city = "Johannesburg"
        biz.latitude, biz.longitude = PLACES[where]
        for svc in services if services is not None else [("Wash & Fold", "wash_and_fold", 2500, 48)]:
            svc_name, category, price, hours = svc
            db.add(LaundryService(
                business=biz, name=svc_name, category=ServiceCategory(category),
                pricing_unit=PricingUnit.PER_KG, price_cents=price, turnaround_hours=hours,
            ))
        db.flush()
        return biz

    return _place


def search(client, **params):
    params = {"lat": JHB[0], "lng": JHB[1]} | params
    r = client.get("/api/laundries", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def names(page):
    return [i["business_name"] for i in page["items"]]


# ---------- Distance ----------

def test_default_radius_is_10km(client, place):
    for where in PLACES:
        place(where)
    assert names(search(client)) == ["Braamfontein Laundry"]


def test_results_sorted_by_distance_with_accurate_km(client, place):
    for where in PLACES:
        place(where)
    page = search(client, radius_km=25)
    assert names(page) == ["Braamfontein Laundry", "Sandton Laundry", "Soweto Laundry"]
    for item, where in zip(page["items"], ["Braamfontein", "Sandton", "Soweto"]):
        expected = haversine_km(*JHB, *PLACES[where])
        assert item["distance_km"] == pytest.approx(expected, abs=0.01)
    assert 10 < page["items"][1]["distance_km"] < 12  # sanity check: Sandton ≈ 11 km


def test_search_is_public(client, place):
    place("Braamfontein")
    r = client.get("/api/laundries", params={"lat": JHB[0], "lng": JHB[1]})
    assert r.status_code == 200  # no Authorization header


# ---------- Who is shown ----------

def test_only_bookable_businesses_are_shown(client, place, db):
    place("Braamfontein", "Approved")
    place("Braamfontein", "Pending", status=V.PENDING)
    place("Braamfontein", "Rejected", status=V.REJECTED)
    place("Braamfontein", "No services", services=[])

    hidden = place("Braamfontein", "Only inactive")
    for s in hidden.services:
        s.is_active = False
    suspended = place("Braamfontein", "Owner suspended")
    suspended.owner.status = AccountStatus.SUSPENDED
    unmapped = place("Braamfontein", "No location")
    unmapped.latitude = unmapped.longitude = None
    db.flush()

    assert names(search(client)) == ["Approved"]


def test_results_contain_no_private_details(client, place):
    biz = place("Braamfontein")
    biz.registration_number = "2020/123456/07"
    page = search(client)
    text = str(page)
    assert biz.owner.email not in text
    assert "2020/123456/07" not in text
    assert "verification_status" not in text


# ---------- Filtering and comparing ----------

def test_category_filter_and_comparison(client, place):
    place("Braamfontein", "Wash only")
    place("Sandton", "Dry cleaner", services=[
        ("Suit", "dry_cleaning", 12000, 72),
        ("Dress", "dry_cleaning", 9000, 48),
    ])
    page = search(client, radius_km=25, category="dry_cleaning")
    assert names(page) == ["Dry cleaner"]
    item = page["items"][0]
    assert item["from_price_cents"] == 9000
    assert item["from_price_display"] == "from R90.00"
    assert item["fastest_turnaround_hours"] == 48
    assert [s["name"] for s in item["matching_services"]] == ["Dress", "Suit"]  # cheapest first


def test_without_category_no_service_list(client, place):
    place("Braamfontein")
    assert search(client)["items"][0]["matching_services"] is None


def test_sort_by_price_requires_category(client):
    r = client.get("/api/laundries", params={"lat": JHB[0], "lng": JHB[1], "sort": "price"})
    assert r.status_code == 422


def test_sort_by_price(client, place):
    place("Braamfontein", "Pricey", services=[("Wash", "wash_and_fold", 4000, 24)])
    place("Sandton", "Cheap", services=[("Wash", "wash_and_fold", 1800, 72)])
    page = search(client, radius_km=25, category="wash_and_fold", sort="price")
    assert names(page) == ["Cheap", "Pricey"]


def test_sort_by_turnaround(client, place):
    place("Braamfontein", "Slow", services=[("Wash", "wash_and_fold", 2000, 72)])
    place("Sandton", "Fast", services=[("Wash", "wash_and_fold", 3000, 6)])
    assert names(search(client, radius_km=25, sort="turnaround")) == ["Fast", "Slow"]


def test_text_search_by_name_or_suburb(client, place):
    place("Braamfontein", "Bubbles & Co")
    place("Sandton", "Fresh Fold")
    assert names(search(client, radius_km=25, q="bubbles")) == ["Bubbles & Co"]
    assert names(search(client, radius_km=25, q="SANDTON")) == ["Fresh Fold"]


def test_text_search_treats_wildcards_literally(client, place):
    place("Braamfontein", "Bubbles")
    assert search(client, q="%")["total"] == 0
    assert search(client, q="_")["total"] == 0


def test_pagination(client, place):
    for i in range(5):
        place("Braamfontein", f"Laundry {i}")
    first = search(client, limit=2)
    rest = search(client, limit=10, offset=2)
    assert first["total"] == 5
    assert len(first["items"]) == 2 and len(rest["items"]) == 3
    assert not set(names(first)) & set(names(rest))


@pytest.mark.parametrize("params", [
    {"radius_km": 51},
    {"radius_km": 0},
    {"lat": 95},
    {"lng": 200},
    {"category": "car_wash"},
])
def test_invalid_search_params(client, params):
    query = {"lat": JHB[0], "lng": JHB[1]} | params
    assert client.get("/api/laundries", params=query).status_code == 422


def test_location_is_required(client):
    assert client.get("/api/laundries").status_code == 422


# ---------- Business page ----------

def test_business_page_shows_active_services_and_distance(client, place, db):
    biz = place("Sandton", services=[
        ("Wash & Fold", "wash_and_fold", 2500, 48),
        ("Duvet", "bedding", 15000, 72),
    ])
    next(s for s in biz.services if s.name == "Duvet").is_active = False
    db.flush()

    r = client.get(f"/api/laundries/{biz.id}", params={"lat": JHB[0], "lng": JHB[1]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [s["name"] for s in body["services"]] == ["Wash & Fold"]
    assert "is_active" not in body["services"][0]
    assert body["distance_km"] == pytest.approx(haversine_km(*JHB, *PLACES["Sandton"]), abs=0.01)
    assert biz.owner.email not in r.text


def test_business_page_without_location_has_no_distance(client, place):
    biz = place("Sandton")
    assert client.get(f"/api/laundries/{biz.id}").json()["distance_km"] is None


@pytest.mark.parametrize("status", [V.PENDING, V.REJECTED])
def test_unapproved_business_page_is_hidden(client, place, status):
    biz = place("Sandton", status=status)
    assert client.get(f"/api/laundries/{biz.id}").status_code == 404
