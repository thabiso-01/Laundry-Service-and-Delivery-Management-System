"""Address search and reverse lookup, proxied to an external geocoder.

Why through the backend instead of straight from the browser:
  * customers' IP addresses aren't sent to the third party (only the text
    they searched for is) – easier to explain under POPIA;
  * Nominatim's usage policy is enforced in one place: at most one request
    per second for the whole app, an identifying User-Agent, and a cache so
    repeated searches don't hit it;
  * per-IP limits stop someone using us as a free geocoding proxy;
  * the provider can be swapped without touching the frontend.
"""

import threading
import time
from collections import OrderedDict, defaultdict, deque
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.config import settings

_CACHE_SIZE = 500
_CACHE_SECONDS = 24 * 3600


class _Cache:
    def __init__(self) -> None:
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            hit = self._items.get(key)
            if hit is None or time.monotonic() - hit[0] > _CACHE_SECONDS:
                return None
            self._items.move_to_end(key)
            return hit[1]

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._items[key] = (time.monotonic(), value)
            self._items.move_to_end(key)
            while len(self._items) > _CACHE_SIZE:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


cache = _Cache()

# One upstream request per second for the whole app (Nominatim policy)
_upstream_lock = threading.Lock()
_last_upstream = 0.0

# Per-IP sliding window
_ip_hits: dict[str, deque[float]] = defaultdict(deque)
_ip_lock = threading.Lock()


def check_rate_limit(ip: str | None) -> None:
    key = ip or "unknown"
    now = time.monotonic()
    with _ip_lock:
        hits = _ip_hits[key]
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= settings.geocoder_requests_per_minute_per_ip:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                "Too many address searches. Wait a minute and try again")
        hits.append(now)


def reset_limits() -> None:
    with _ip_lock:
        _ip_hits.clear()


def _fetch(path: str, params: dict[str, Any]) -> Any:
    """Calls the geocoder, politely. Separate so tests can replace it."""
    global _last_upstream
    with _upstream_lock:
        wait = 1.0 - (time.monotonic() - _last_upstream)
        if wait > 0:
            time.sleep(wait)
        try:
            response = httpx.get(
                f"{settings.geocoder_url}{path}",
                params={**params, "format": "jsonv2", "addressdetails": 1},
                headers={"User-Agent": settings.geocoder_user_agent, "Accept-Language": "en"},
                timeout=8,
            )
        finally:
            _last_upstream = time.monotonic()
    response.raise_for_status()
    return response.json()


def _to_address(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        lat, lng = float(item["lat"]), float(item["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    a = item.get("address") or {}
    street = " ".join(p for p in (a.get("house_number"), a.get("road")) if p)
    return {
        "label": item.get("display_name") or street,
        "address_line": street or a.get("building") or a.get("amenity") or item.get("name") or "",
        "suburb": a.get("suburb") or a.get("neighbourhood") or a.get("quarter") or a.get("city_district"),
        "city": a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or a.get("county"),
        "province": a.get("state"),
        "postal_code": a.get("postcode"),
        "latitude": round(lat, 6),
        "longitude": round(lng, 6),
    }


def _call(key: str, path: str, params: dict[str, Any]) -> Any:
    if not settings.geocoder_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Address search is switched off. Enter the address by hand")
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        data = _fetch(path, params)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Address search isn't available right now. Enter the address by hand")
    cache.put(key, data)
    return data


def search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    q = " ".join(query.split())
    data = _call(f"search:{q.lower()}:{limit}", "/search",
                 {"q": q, "limit": limit, "countrycodes": settings.geocoder_country_codes})
    return [a for a in (_to_address(i) for i in data or []) if a]


def reverse(lat: float, lng: float) -> dict[str, Any] | None:
    # ~11 m grid for the cache key: nearby taps share a lookup
    data = _call(f"reverse:{lat:.4f}:{lng:.4f}", "/reverse", {"lat": lat, "lon": lng, "zoom": 18})
    if not isinstance(data, dict) or "error" in data:
        return None
    return _to_address(data)
