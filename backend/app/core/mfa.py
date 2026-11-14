"""Authenticator-app codes (TOTP, RFC 6238) and recovery codes (SEC-039).

Works with Google Authenticator, Microsoft Authenticator, Authy, etc.
The shared secret is encrypted at rest (Fernet, key derived from the server
secret); recovery codes are random and stored only as SHA-256 hashes.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1  # accept the previous/next 30 s step, for phone clock drift


def _fernet() -> Fernet:
    key = hashlib.sha256(b"laundryconnect:mfa:" + settings.jwt_secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def encrypt(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def provisioning_uri(secret: str, account: str) -> str:
    """otpauth:// link – shown as a QR code for the authenticator app to scan."""
    issuer = quote(settings.mfa_issuer)
    return (f"otpauth://totp/{issuer}:{quote(account)}?secret={secret}&issuer={issuer}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")


def _code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10 ** DIGITS:0{DIGITS}d}"


def current_step(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // STEP_SECONDS)


def code_for(secret: str, now: float | None = None) -> str:
    return _code_at(secret, current_step(now))


def verify(secret: str, code: str, last_step: int | None) -> int | None:
    """Returns the matched time step (to store, so the same code can't be
    replayed), or None if the code is wrong or already used."""
    code = code.strip()
    if not (code.isdigit() and len(code) == DIGITS):
        return None
    now = current_step()
    for step in range(now - WINDOW, now + WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(_code_at(secret, step), code):
            return step
    return None


def new_recovery_codes(count: int = 8) -> list[str]:
    alphabet = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
    return ["-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2))
            for _ in range(count)]


def hash_recovery(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()
