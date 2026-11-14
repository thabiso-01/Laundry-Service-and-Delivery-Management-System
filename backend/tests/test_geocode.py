"""Address search proxy (map pickers). The real geocoder is never called."""

import httpx
import pytest

from app.config import settings
from app.services import geocode

# Captured at import, before the autouse fixture swaps in its network blocker
REAL_FETCH = geocode._fetch

BRAAM = {
    "lat": "-26.1929", "lon": "28.0305",
    "display_name": "45, Juta Street, Braamfontein, Johannesburg, Gauteng, 2001, South Africa",
    "address": {"house_number": "45", "road": "Juta Street", "suburb": "Braamfontein",
                "city": "Johannesburg", "state": "Gauteng", "postcode": "2001",
                "country_code": "za"},
}


@pytest.fixture
def upstream(monkeypatch):
    """A fake geocoder that records what it was asked."""
    calls = []

    def fake(path, params):
        calls.append((path, params))
        if path == "/search":
            return [BRAAM, {"lat": "bad"}]  # the broken entry must be skipped
        if params["lat"] > 0:
            return {"error": "Unable to geocode"}
        return BRAAM

    monkeypatch.setattr(geocode, "_fetch", fake)
    return calls


def test_search_returns_clean_addresses(client, upstream):
    r = client.get("/api/geocode", params={"q": "45 Juta St Braamfontein"})
    assert r.status_code == 200, r.text
    assert r.json() == [{
        "label": BRAAM["display_name"], "address_line": "45 Juta Street",
        "suburb": "Braamfontein", "city": "Johannesburg", "province": "Gauteng",
        "postal_code": "2001", "latitude": -26.1929, "longitude": 28.0305,
    }]
    path, params = upstream[0]
    assert path == "/search"
    assert params["countrycodes"] == "za"  # South Africa only


def test_search_is_cached(client, upstream):
    for q in ("Juta St", "  juta   st "):  # same search, different spacing/case
        assert client.get("/api/geocode", params={"q": q}).status_code == 200
    assert len(upstream) == 1


def test_reverse_lookup(client, upstream):
    r = client.get("/api/geocode/reverse", params={"lat": -26.1929, "lng": 28.0305})
    assert r.json()["address_line"] == "45 Juta Street"
    # Taps a few metres apart share one lookup
    client.get("/api/geocode/reverse", params={"lat": -26.19291, "lng": 28.03052})
    assert len(upstream) == 1


def test_reverse_nothing_found(client, upstream):
    r = client.get("/api/geocode/reverse", params={"lat": 10, "lng": 10})
    assert r.status_code == 404


def test_query_too_short(client, upstream):
    assert client.get("/api/geocode", params={"q": "ab"}).status_code == 422
    assert upstream == []


def test_per_ip_rate_limit(client, upstream, monkeypatch):
    monkeypatch.setattr(settings, "geocoder_requests_per_minute_per_ip", 3)
    codes = [client.get("/api/geocode", params={"q": f"street {i}"}).status_code for i in range(4)]
    assert codes == [200, 200, 200, 429]


def test_geocoder_down_gives_friendly_error(client, monkeypatch):
    def down(path, params):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(geocode, "_fetch", down)
    r = client.get("/api/geocode", params={"q": "Juta Street"})
    assert r.status_code == 503
    assert "Enter the address by hand" in r.json()["detail"]


def test_can_be_switched_off(client, upstream, monkeypatch):
    monkeypatch.setattr(settings, "geocoder_enabled", False)
    assert client.get("/api/geocode", params={"q": "Juta Street"}).status_code == 503
    assert upstream == []


def test_upstream_is_called_politely(monkeypatch):
    """At most one request per second, with an identifying User-Agent."""
    sent = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return []

    def fake_get(url, params, headers, timeout):
        sent.append((url, headers["User-Agent"], geocode.time.monotonic()))
        return Response()

    # The real _fetch, with the network itself faked
    monkeypatch.setattr(geocode.httpx, "get", fake_get)
    REAL_FETCH("/search", {"q": "a"})
    REAL_FETCH("/search", {"q": "b"})
    assert sent[0][0].endswith("/search")
    assert sent[0][1] == settings.geocoder_user_agent
    assert sent[1][2] - sent[0][2] >= 0.95
