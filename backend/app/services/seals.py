"""Tamper-evident bag seals (SEC-025 – SEC-028).

At the start of a trip the driver records the seal numbers on the bag(s). At
the end, the receiver checks them. Any missing, unexpected or broken seal
automatically opens a high-severity incident – the handover itself still
goes ahead, because the bag is physically there and must be looked after.
"""

import re
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BagSeal, Incident, Order, User
from app.models.enums import (
    IncidentCategory,
    IncidentSeverity,
    JobKind,
    SealCheck,
)
from app.services import audit, incidents

_SEAL_RE = re.compile(r"^[A-Z0-9-]{4,20}$")


def normalise(numbers: list[str]) -> list[str]:
    cleaned = [re.sub(r"\s", "", n).upper() for n in numbers]
    for n in cleaned:
        if not _SEAL_RE.match(n):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"'{n}' is not a valid seal number (4–20 letters, digits or -)")
    if len(set(cleaned)) != len(cleaned):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "The same seal number was entered twice")
    return cleaned


def ensure_unused(db: Session, order: Order, numbers: list[str], actor: User,
                  request: Request) -> list[str]:
    """Validates seal numbers and refuses any already used on the platform.
    Call this BEFORE changing anything else: on refusal it commits the audit
    entry, which would also commit any other pending change."""
    numbers = normalise(numbers)
    used = db.scalars(select(BagSeal.seal_number).where(BagSeal.seal_number.in_(numbers))).all()
    if used:
        # A seal that was already used elsewhere could hide a re-opened bag
        audit.record(db, "seal.reuse_attempt", actor_id=actor.id, entity_type="order",
                     entity_id=order.id, details={"seal_numbers": sorted(used)}, request=request)
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Seal {', '.join(sorted(used))} has already been used. "
                            "Use a new, unused seal")
    return numbers


def record(order: Order, leg: JobKind, numbers: list[str], actor: User) -> list[BagSeal]:
    """Registers the seals put on the bag(s) for this trip (SEC-025, SEC-026).
    `numbers` must come from ensure_unused()."""
    seals = [BagSeal(leg=leg, seal_number=n, recorded_by_id=actor.id) for n in numbers]
    order.seals.extend(seals)
    return seals


def check(
    db: Session, order: Order, leg: JobKind, seen: list[str], intact: bool, actor: User,
    request: Request,
) -> Incident | None:
    """Compares the seals the receiver sees with the ones recorded (SEC-027).
    Returns the incident opened if something is wrong (SEC-028)."""
    seen_set = set(normalise(seen)) if seen else set()
    expected = [s for s in order.seals if s.leg == leg]
    expected_set = {s.seal_number for s in expected}
    missing = sorted(expected_set - seen_set)
    unexpected = sorted(seen_set - expected_set)

    now = datetime.now(UTC)
    for seal in expected:
        seal.check_result = (SealCheck.MISSING if seal.seal_number in missing
                             else SealCheck.INTACT if intact else SealCheck.BROKEN)
        seal.checked_by_id = actor.id
        seal.checked_at = now

    if intact and not missing and not unexpected:
        return None

    problems = []
    if not intact:
        problems.append("seal(s) reported broken or tampered with")
    if missing:
        problems.append(f"expected seal(s) not found: {', '.join(missing)}")
    if unexpected:
        problems.append(f"unexpected seal(s) on the bag: {', '.join(unexpected)}")
    stage = "collection" if leg == JobKind.COLLECTION else "delivery"
    incident = incidents.open_incident(
        db, reporter=actor,
        category=IncidentCategory.BROKEN_SEAL if not intact else IncidentCategory.SEAL_MISMATCH,
        description=f"Seal check failed at the end of the {stage} trip for order "
                    f"{order.order_number}: " + "; ".join(problems) + ".",
        order=order, request=request, automatic=True, severity=IncidentSeverity.HIGH,
    )
    audit.record(db, "seal.check_failed", actor_id=actor.id, entity_type="order",
                 entity_id=order.id,
                 details={"leg": leg.value, "intact": intact, "missing": missing,
                          "unexpected": unexpected, "incident": incident.reference},
                 request=request)
    return incident
