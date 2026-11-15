"""Your personal information: download it or delete your account (POPIA s23, s24)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession
from app.services import privacy

router = APIRouter(prefix="/api/me", tags=["privacy"])


class DeleteAccountIn(BaseModel):
    password: str = Field(max_length=128)
    code: str | None = Field(default=None, max_length=20, description="Needed if two-step login is on")
    confirm: str = Field(pattern="^DELETE$", description='Type "DELETE" to confirm')


class DeleteAccountOut(BaseModel):
    deleted: bool
    removed: dict[str, int]
    kept: list[str]


@router.get("/data-export")
def download_my_data(user: CurrentUser, db: DbSession, request: Request) -> JSONResponse:
    """Everything we hold about you, as a JSON file."""
    data = privacy.export(db, user, request)
    name = f"laundryconnect-my-data-{datetime.now(UTC):%Y-%m-%d}.json"
    return JSONResponse(data, headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "Cache-Control": "no-store, private",
    })


@router.delete("", response_model=DeleteAccountOut)
def delete_my_account(body: DeleteAccountIn, user: CurrentUser, db: DbSession,
                      request: Request) -> dict:
    """Permanently delete your account. Records the law requires us to keep are
    stripped of your details; the response lists what was removed and kept."""
    return privacy.delete_account(db, user, body.password, body.code, request)
