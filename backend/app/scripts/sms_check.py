"""Send one test SMS to check your SMS settings.

    cd backend
    python -m app.scripts.sms_check --to "082 123 4567"

Uses SMS_PROVIDER (log | bulksms) and, for BulkSMS, BULKSMS_TOKEN_ID /
BULKSMS_TOKEN_SECRET (BulkSMS: Settings > Developer Settings > API Tokens).
A real SMS costs a credit.
"""

import argparse
import random
import sys

from app.config import settings
from app.schemas.validators import normalise_sa_phone
from app.services import sms


def main() -> int:
    parser = argparse.ArgumentParser(description="Send one test SMS")
    parser.add_argument("--to", required=True, help="South African mobile number")
    args = parser.parse_args()
    try:
        to = normalise_sa_phone(args.to)
    except ValueError as e:
        print(e)
        return 1
    print(f"Provider: {settings.sms_provider}. Sending a test SMS to {to}...")
    try:
        message_id = sms.send(to, "LaundryConnect: test message. Your SMS settings work.",
                              random.randint(1, 2**31 - 1))
    except sms.SmsError as e:
        print(f"FAILED: {e}")
        return 1
    print(f"OK, accepted by {settings.sms_provider} (message id {message_id}).")
    if settings.sms_provider == "log":
        print("(log provider: nothing was really sent. Set SMS_PROVIDER=bulksms to send.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
