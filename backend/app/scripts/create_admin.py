"""Create an administrator account from the command line (SEC-020).

Admins can't sign up through the API – only someone with server access can
create one:

    cd backend
    python -m app.scripts.create_admin --email admin@example.co.za --name "Jane Admin"

You will be asked for the password (it is not echoed or stored in shell history).
"""

import argparse
import getpass
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.security import hash_password
from app.database import SessionLocal
from app.models import User
from app.models.enums import AccountStatus, UserRole
from app.services import audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a LaundryConnect administrator")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, help="Full name")
    args = parser.parse_args()
    email = args.email.strip().lower()

    password = getpass.getpass("Password (min 10 characters): ")
    if len(password) < 10:
        print("Password must be at least 10 characters.", file=sys.stderr)
        return 1
    if getpass.getpass("Repeat password: ") != password:
        print("Passwords do not match.", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)):
            print(f"An account with {email} already exists.", file=sys.stderr)
            return 1
        admin = User(
            email=email,
            full_name=args.name.strip(),
            password_hash=hash_password(password),
            role=UserRole.ADMIN,
            status=AccountStatus.ACTIVE,
            email_verified=True,
            privacy_consent_at=datetime.now(UTC),
        )
        db.add(admin)
        db.flush()
        audit.record(db, "admin.created_via_cli", actor_id=admin.id,
                     entity_type="user", entity_id=admin.id)
        db.commit()
        print(f"Administrator {email} created.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
