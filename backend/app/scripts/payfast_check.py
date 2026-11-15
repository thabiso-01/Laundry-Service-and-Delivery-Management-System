"""Check your PayFast credentials and our signatures against PayFast itself.

    cd backend
    python -m app.scripts.payfast_check

Posts a small signed test payment form to PayFast (sandbox unless
PAYFAST_SANDBOX=false) – it doesn't take any money – and reports whether
PayFast accepts the signature. Run it after setting PAYFAST_MERCHANT_ID,
PAYFAST_MERCHANT_KEY and PAYFAST_PASSPHRASE.

"Generated signature does not match" almost always means the passphrase in
.env differs from the one set in the PayFast dashboard (Settings → Developer
Settings → Salt Passphrase), or that one is set and the other isn't.
"""

import re
import sys
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.services import payfast


def main() -> int:
    pairs = [
        ("merchant_id", settings.payfast_merchant_id),
        ("merchant_key", settings.payfast_merchant_key),
        ("return_url", f"{settings.public_app_url}/"),
        ("cancel_url", f"{settings.public_app_url}/"),
        ("notify_url", f"{settings.public_api_url}/api/payments/payfast/notify"),
        ("m_payment_id", "PAY-CREDCHECK01"),
        ("amount", "10.00"),
        ("item_name", "LaundryConnect credential check"),
    ]
    pairs.append(("signature", payfast.signature(pairs, settings.payfast_passphrase)))
    url = f"{payfast.base_url()}/eng/process"
    print(f"Posting a signed test form to {url} (merchant {settings.payfast_merchant_id}, "
          f"passphrase {'set' if settings.payfast_passphrase else 'NOT set'})")
    try:
        r = httpx.post(url, content=urlencode(pairs), follow_redirects=True, timeout=30,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
    except httpx.HTTPError as e:
        print(f"Couldn't reach PayFast: {e}")
        return 2
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))
    problems = re.findall(r"information provided by the seller is invalid:? ([^.]{0,200})", text, re.I)
    if problems or r.status_code >= 400:
        print(f"PayFast REJECTED the form (HTTP {r.status_code}): {problems[0].strip() if problems else text[:200]}")
        if "signature" in text.lower():
            print("-> Check PAYFAST_PASSPHRASE matches the Salt Passphrase in your PayFast dashboard.")
        return 1
    print(f"PayFast ACCEPTED the signed form (HTTP {r.status_code}): credentials and signatures are correct.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
