"""Create demo accounts for trying the app locally. NEVER run this in production.

    cd backend
    python -m app.scripts.seed_demo --yes

Creates (skipping any that already exist), all with password DemoPass#2026:
    admin@demo.lc      administrator
    customer@demo.lc   customer (Marshalltown, Johannesburg)
    owner@demo.lc      owner of "Braam Fresh Laundry" – approved, with services
    attendant@demo.lc  attendant at that laundry
    driver1@demo.lc    approved driver (motorcycle)
    driver2@demo.lc    approved driver (car)

To start again from an empty database:  docker compose down -v && docker compose up -d
then  alembic upgrade head  and run this script again.
"""

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.security import hash_password
from app.database import SessionLocal
from app.models import (
    BusinessProfile,
    BusinessStaff,
    CustomerProfile,
    DriverProfile,
    LaundryService,
    User,
)
from app.models.enums import (
    AccountStatus,
    BusinessStaffRole,
    PricingUnit,
    ServiceCategory,
    UserRole,
    VehicleType,
    VerificationStatus,
)
from app.services import audit

PASSWORD = "DemoPass#2026"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--yes", action="store_true", help="confirm this is a dev database")
    if not parser.parse_args().yes:
        print("Refusing to run without --yes. This adds demo accounts with a public password.")
        return 1

    now = datetime.now(UTC)
    with SessionLocal() as db:
        created = []

        def user(email: str, name: str, role: UserRole, phone: str | None = None) -> User | None:
            if db.scalar(select(User).where(User.email == email)):
                return None
            u = User(email=email, full_name=name, role=role, phone=phone,
                     password_hash=hash_password(PASSWORD), status=AccountStatus.ACTIVE,
                     privacy_consent_at=now, email_verified=True)
            db.add(u)
            created.append((email, role.value))
            return u

        user("admin@demo.lc", "Ayanda Admin", UserRole.ADMIN)

        if c := user("customer@demo.lc", "Thandi Mokoena", UserRole.CUSTOMER, "+27821110001"):
            c.customer_profile = CustomerProfile(address_line="12 Pritchard St", suburb="Marshalltown",
                                                 city="Johannesburg", latitude=-26.2041, longitude=28.0473)

        if owner := user("owner@demo.lc", "Pieter van Wyk", UserRole.BUSINESS, "+27821110002"):
            biz = BusinessProfile(
                owner=owner, business_name="Braam Fresh Laundry", registration_number="2019/555123/07",
                description="Family-run laundry and dry cleaner in Braamfontein. Same-day ironing.",
                contact_phone="+27113334444", address_line="45 Juta St", suburb="Braamfontein",
                city="Johannesburg", province="Gauteng", latitude=-26.1929, longitude=28.0305,
                verification_status=VerificationStatus.APPROVED, verified_at=now,
            )
            biz.staff.append(BusinessStaff(user=owner, staff_role=BusinessStaffRole.OWNER))
            for name, cat, unit, price, hours, minimum in [
                ("Wash & Fold", ServiceCategory.WASH_AND_FOLD, PricingUnit.PER_KG, 2500, 48, 3),
                ("Wash & Iron", ServiceCategory.WASH_AND_IRON, PricingUnit.PER_KG, 3800, 48, 3),
                ("Shirt ironing", ServiceCategory.IRONING, PricingUnit.PER_ITEM, 1500, 24, 1),
                ("Suit dry clean", ServiceCategory.DRY_CLEANING, PricingUnit.PER_ITEM, 12000, 72, 1),
                ("Duvet (double)", ServiceCategory.BEDDING, PricingUnit.PER_ITEM, 15000, 72, 1),
            ]:
                biz.services.append(LaundryService(name=name, category=cat, pricing_unit=unit,
                                                   price_cents=price, turnaround_hours=hours,
                                                   min_quantity=minimum))
            db.add(biz)
            db.flush()
            if att := user("attendant@demo.lc", "Lerato Dlamini", UserRole.BUSINESS):
                db.add(BusinessStaff(business=biz, user=att, staff_role=BusinessStaffRole.ATTENDANT,
                                     added_by_id=owner.id))

        for n, (name, vehicle, reg, id_no) in enumerate([
            ("Sipho Ndlovu", VehicleType.MOTORCYCLE, "GP 123-456", "P1000001"),
            ("Naledi Khumalo", VehicleType.CAR, "GP 789-012", "P1000002"),
        ], start=1):
            if d := user(f"driver{n}@demo.lc", name, UserRole.DRIVER, f"+2782111001{n}"):
                d.driver_profile = DriverProfile(
                    id_number=id_no, vehicle_type=vehicle, vehicle_registration=reg,
                    verification_status=VerificationStatus.APPROVED, verified_at=now)

        db.flush()
        audit.record(db, "demo.seeded", details={"accounts": [e for e, _ in created]})
        db.commit()

    if created:
        print(f"Created {len(created)} demo account(s); password for all: {PASSWORD}")
        for email, role in created:
            print(f"  {role:<9} {email}")
    else:
        print("Demo accounts already exist; nothing to do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
