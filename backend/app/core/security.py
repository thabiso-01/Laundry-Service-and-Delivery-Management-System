"""Password hashing and login tokens (SEC-038)."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.config import settings

# Argon2id – the current recommended algorithm for password storage
_hasher = PasswordHash.recommended()

# Verified against when the email doesn't exist, so a failed login takes the
# same time whether or not the account exists (stops account discovery by timing).
DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-real-password")


_TEMP_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"  # no 0/O, 1/l/I


def generate_temporary_password(length: int = 12) -> str:
    """Random one-time password that is easy to read out or type from a slip."""
    return "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(length))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, str | None]:
    """Returns (is_valid, new_hash). new_hash is set when the stored hash uses
    outdated parameters and should be replaced."""
    return _hasher.verify_and_update(password, password_hash)


def create_access_token(user_id: uuid.UUID, role: str) -> tuple[str, int]:
    """Returns (token, lifetime_in_seconds)."""
    lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "role": role,  # informational only – permissions are always re-checked from the DB
        "type": "access",
        "iat": now,
        "exp": now + lifetime,
    }
    token = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, int(lifetime.total_seconds())


MFA_TOKEN_SECONDS = 300


def create_mfa_token(user_id: uuid.UUID) -> tuple[str, int]:
    """Short-lived proof that the password step passed; useless as a login token."""
    now = datetime.now(UTC)
    claims = {"sub": str(user_id), "type": "mfa", "iat": now,
              "exp": now + timedelta(seconds=MFA_TOKEN_SECONDS)}
    return jwt.encode(claims, settings.jwt_secret_key,
                      algorithm=settings.jwt_algorithm), MFA_TOKEN_SECONDS


def decode_mfa_token(token: str) -> dict[str, Any] | None:
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm],
                            options={"require": ["sub", "exp", "iat"]})
    except jwt.InvalidTokenError:
        return None
    return claims if claims.get("type") == "mfa" else None


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Returns the claims, or None if the token is invalid, tampered with or expired."""
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.InvalidTokenError:
        return None
    if claims.get("type") != "access":
        return None
    return claims
