"""Signed order QR codes (SEC-010 – SEC-012).

Code format (uppercase letters, digits and ".-" only, so it fits QR
"alphanumeric" mode and stays small and easy to scan off a bag label):

    LCQ1.LC-7K3M9QX2.1.ABCDEFGHJKMNPQRS
    │    │           │ └ signature: HMAC-SHA256, 80 bits, Crockford base32
    │    │           └ version: bumped when a label is lost or copied
    │    └ order number
    └ format marker

The signature key is derived from the server secret, so codes can't be forged
or edited (e.g. swapping the order number) without detection.
"""

import base64
import hashlib
import hmac
import io
import re
from dataclasses import dataclass
from enum import StrEnum

import segno

from app.config import settings
from app.models import Order

PREFIX = "LCQ1"
_CODE_RE = re.compile(r"^LCQ1\.(LC-[0-9A-Z]{8})\.([1-9][0-9]{0,5})\.([0-9A-Z]{16})$")
# Standard base32 alphabet → Crockford's, which avoids I, L, O and U
_B32_TO_CROCKFORD = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567",
                                  "0123456789ABCDEFGHJKMNPQRSTVWXYZ")


def _key() -> bytes:
    # A separate key per purpose, so a login token can never pass as a QR signature
    return hashlib.sha256(b"laundryconnect:qr:" + settings.jwt_secret_key.encode()).digest()


def _sign(order_number: str, version: int) -> str:
    mac = hmac.new(_key(), f"{order_number}.{version}".encode(), hashlib.sha256).digest()
    return base64.b32encode(mac[:10]).decode().translate(_B32_TO_CROCKFORD)


def code_for(order: Order) -> str:
    return f"{PREFIX}.{order.order_number}.{order.qr_version}.{_sign(order.order_number, order.qr_version)}"


class Problem(StrEnum):
    MALFORMED = "malformed"          # not one of our codes at all
    BAD_SIGNATURE = "bad_signature"  # looks right but was forged or edited
    UNKNOWN_ORDER = "unknown_order"
    REPLACED = "replaced"            # an older label for an order whose code was reissued


@dataclass
class Parsed:
    order_number: str
    version: int


def parse(code: str) -> Parsed | Problem:
    """Checks the format and signature only; the caller looks up the order."""
    match = _CODE_RE.match(code.strip().upper())
    if not match:
        return Problem.MALFORMED
    order_number, version, signature = match.group(1), int(match.group(2)), match.group(3)
    if not hmac.compare_digest(signature, _sign(order_number, version)):
        return Problem.BAD_SIGNATURE
    return Parsed(order_number, version)


def render(code: str, fmt: str) -> tuple[bytes, str]:
    """Returns (image bytes, media type). Error correction "Q" tolerates ~25%
    damage – a crumpled or splashed bag label still scans."""
    qr = segno.make(code, error="q", micro=False)
    buffer = io.BytesIO()
    if fmt == "svg":
        qr.save(buffer, kind="svg", scale=8, border=4, xmldecl=False)
        return buffer.getvalue(), "image/svg+xml"
    qr.save(buffer, kind="png", scale=8, border=4)
    return buffer.getvalue(), "image/png"
