"""Admin approval / rejection of drivers and businesses (UR-004, SEC-003, SEC-043).

Status transitions:

    pending  ──approve──▶ approved
    pending  ──reject───▶ rejected
    rejected ──approve──▶ approved   (re-review after the user fixes the problem)
    approved ──reject───▶ rejected   (revoke approval, e.g. during an investigation)

Approving something already approved, or rejecting something already
rejected, is refused so the audit trail only contains real decisions.
"""

from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.models import BusinessProfile, DriverProfile, User
from app.models.enums import VerificationStatus
from app.services import audit, jobs

Reviewable = DriverProfile | BusinessProfile


def _entity(profile: Reviewable) -> tuple[str, str]:
    if isinstance(profile, DriverProfile):
        return "driver", str(profile.user_id)
    return "business", str(profile.id)


def approve(db: Session, profile: Reviewable, admin: User, request: Request | None) -> None:
    previous = profile.verification_status
    if previous == VerificationStatus.APPROVED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already approved")

    profile.verification_status = VerificationStatus.APPROVED
    profile.verified_by_id = admin.id
    profile.verified_at = datetime.now(UTC)
    profile.rejection_reason = None

    kind, entity_id = _entity(profile)
    audit.record(db, f"{kind}.approved", actor_id=admin.id, entity_type=f"{kind}_profile",
                 entity_id=entity_id, details={"previous_status": previous.value},
                 request=request)
    db.commit()


def reject(
    db: Session, profile: Reviewable, admin: User, reason: str, request: Request | None
) -> None:
    previous = profile.verification_status
    if previous == VerificationStatus.REJECTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already rejected")

    profile.verification_status = VerificationStatus.REJECTED
    profile.verified_by_id = admin.id
    profile.verified_at = datetime.now(UTC)
    profile.rejection_reason = reason
    released = 0
    if isinstance(profile, DriverProfile):
        # A driver whose approval is revoked must stop receiving jobs at once,
        # and jobs they haven't picked up yet go back on the board (SEC-004)
        profile.is_available = False
        released = jobs.release_all_for_driver(db, profile.user, reason)

    kind, entity_id = _entity(profile)
    audit.record(db, f"{kind}.rejected", actor_id=admin.id, entity_type=f"{kind}_profile",
                 entity_id=entity_id,
                 details={"previous_status": previous.value, "reason": reason,
                          **({"jobs_released": released} if released else {})},
                 request=request)
    db.commit()
