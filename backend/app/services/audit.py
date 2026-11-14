"""Helper for writing audit log entries (SEC-041)."""

import ipaddress
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog


def _client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    try:
        return str(ipaddress.ip_address(request.client.host))
    except ValueError:  # e.g. the test client reports "testclient"
        return None


def apply_changes(obj: Any, updates: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Sets the given attributes and returns {field: {"from": old, "to": new}}
    for those that actually changed, ready to store in the audit details."""
    diff: dict[str, dict[str, Any]] = {}
    for field, new in updates.items():
        old = getattr(obj, field)
        if old != new:
            setattr(obj, field, new)
            as_json = lambda v: v.value if hasattr(v, "value") else v  # noqa: E731
            diff[field] = {"from": as_json(old), "to": as_json(new)}
    return diff


def record(
    db: Session,
    action: str,
    *,
    actor_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: Any = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    """Adds an audit entry to the current transaction. The caller commits, so the
    entry is saved together with the change it describes, or not at all."""
    user_agent = request.headers.get("user-agent") if request else None
    db.add(
        AuditLog(
            actor_user_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=details,
            ip_address=_client_ip(request),
            user_agent=user_agent[:500] if user_agent else None,
        )
    )
