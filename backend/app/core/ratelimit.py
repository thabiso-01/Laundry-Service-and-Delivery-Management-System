"""Per-IP rate limiting (SEC-038, SEC-040).

Account lockout stops guessing one account's password; these limits stop one
network guessing passwords across *many* accounts, mass-registering fake
accounts, or spamming reports.

Counts live in memory (sliding window), which suits a single API process. For
several processes or servers, implement `Limiter.hit` on Redis (INCR + EXPIRE)
behind the same interface.

Use on a route:
    @router.post("/login", dependencies=[Depends(rate_limit("login", lambda: 10, 60))])
"""

import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db

_MAX_KEYS = 100_000  # protects memory if someone rotates through many IPs


class Limiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._blocked_until: dict[str, float] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def hit(self, key: str, limit: int, window: float) -> tuple[bool, float, bool]:
        """Counts one request. Returns (allowed, retry_after_seconds, first_block),
        where first_block is True only for the first refusal in a window – used
        to log it once instead of on every attempt."""
        now = self.clock()
        with self._lock:
            self._calls += 1
            if self._calls % 1000 == 0:
                self._cleanup(now)
            hits = self._hits[key]
            while hits and now - hits[0] >= window:
                hits.popleft()
            if len(hits) >= limit:
                retry = window - (now - hits[0])
                first = self._blocked_until.get(key, 0) <= now
                self._blocked_until[key] = now + retry
                return False, retry, first
            hits.append(now)
            return True, 0.0, False

    def _cleanup(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v]:
            del self._hits[key]
        for key in [k for k, until in self._blocked_until.items() if until <= now]:
            del self._blocked_until[key]
        if len(self._hits) > _MAX_KEYS:  # extreme case: start again rather than run out of memory
            self._hits.clear()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._blocked_until.clear()


limiter = Limiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def check(request: Request, db: Session, name: str, limit: int, window: float,
          message: str = "Too many requests from your network. Please wait and try again") -> None:
    """Raises 429 when the IP is over the limit for this rule. The first refusal
    in each window is written to the audit log (SEC-040)."""
    if not settings.ratelimit_enabled:
        return
    ip = client_ip(request)
    allowed, retry, first = limiter.hit(f"{name}:{ip}", limit, window)
    if allowed:
        return
    if first:
        from app.services import audit
        try:
            audit.record(db, "ratelimit.blocked",
                         details={"rule": name, "limit": limit, "window_seconds": window, "ip": ip},
                         request=request)
            db.commit()
        except Exception:  # logging must never turn a 429 into a 500
            db.rollback()
    raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message,
                        headers={"Retry-After": str(max(1, math.ceil(retry)))})


def rate_limit(name: str, limit: Callable[[], int], window: float):
    """Route dependency. `limit` is read on each request so settings can change."""

    def dependency(request: Request, db: Session = Depends(get_db)) -> None:
        check(request, db, name, limit(), window)

    return Depends(dependency)
