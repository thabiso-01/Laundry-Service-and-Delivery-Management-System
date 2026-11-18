"""Create demo data for trying the app locally. NEVER run this in production.

    cd backend
    python -m app.scripts.seed_demo --yes

Creates (skipping anything that already exists), all with password DemoPass#2026:
    admin@demo.lc        administrator
    admin2@demo.lc, admin3@demo.lc   more administrators
    customer@demo.lc     customer (Marshalltown, Johannesburg) – used by the e2e tests
    lindiwe@demo.lc, johan@demo.lc, ayesha@demo.lc, kagiso@demo.lc   more customers
    owner@demo.lc        owner of "Braam Fresh Laundry" – approved, with services
    attendant@demo.lc    attendant at that laundry
    owner2..owner5@demo.lc   owners of four more laundries around Johannesburg
    driver1@demo.lc      approved driver (motorcycle)
    driver2@demo.lc      approved driver (car)
    driver3@demo.lc      driver waiting for approval (for the admin screens)
    owner6@demo.lc       laundry waiting for approval (for the admin screens)

New laundries also get a shop photo and a history of delivered orders with
reviews from the demo customers, so ratings look like a real marketplace.

To start again from an empty database:  docker compose down -v && docker compose up -d
then  alembic upgrade head  and run this script again.
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.security import hash_password
from app.database import SessionLocal
from app.models import (
    BusinessProfile,
    BusinessStaff,
    CustomerProfile,
    DriverProfile,
    LaundryService,
    Order,
    OrderItem,
    Review,
    User,
)
from app.models.enums import (
    AccountStatus,
    BusinessStaffRole,
    OrderStatus,
    PricingUnit,
    ReviewTarget,
    ServiceCategory,
    UserRole,
    VehicleType,
    VerificationStatus,
)
from app.services import audit, covers, storage
from app.services.orders import new_order_number

PASSWORD = "DemoPass#2026"
PHOTOS = Path(__file__).resolve().parents[3] / "frontend" / "public" / "images"

C, K, I = ServiceCategory, PricingUnit.PER_KG, PricingUnit.PER_ITEM

# (owner email, owner name, business, suburb, lat, lng, description, photo, services, reviews)
# services: (name, category, unit, price_cents, hours, minimum)
# reviews: (customer email, rating, comment, days ago)
LAUNDRIES = [
    ("owner@demo.lc", "Pieter van Wyk", "Braam Fresh Laundry", "Braamfontein", -26.1929, 28.0305,
     "Family-run laundry and dry cleaner in Braamfontein. Same-day ironing.", "hero-linen.jpg",
     [("Wash & Fold", C.WASH_AND_FOLD, K, 2500, 48, 3), ("Wash & Iron", C.WASH_AND_IRON, K, 3800, 48, 3),
      ("Shirt ironing", C.IRONING, I, 1500, 24, 1), ("Suit dry clean", C.DRY_CLEANING, I, 12000, 72, 1),
      ("Duvet (double)", C.BEDDING, I, 15000, 72, 1)],
     [("lindiwe@demo.lc", 5, "Shirts came back perfectly pressed. Driver was on time.", 40),
      ("johan@demo.lc", 4, "Good service, collection was a bit late but they messaged me.", 26),
      ("ayesha@demo.lc", 5, "My duvet smells amazing. Will use again!", 12)]),
    ("owner2@demo.lc", "Nomsa Sithole", "Melville Wash Co.", "Melville", -26.1767, 28.0083,
     "Eco-friendly washing with biodegradable detergents. Express 24-hour wash & fold.", "cover-laundromat.jpg",
     [("Express Wash & Fold", C.WASH_AND_FOLD, K, 2200, 24, 3), ("Wash & Iron", C.WASH_AND_IRON, K, 3500, 48, 3),
      ("Shirt ironing", C.IRONING, I, 1200, 24, 1), ("Duvet (queen)", C.BEDDING, I, 14000, 48, 1),
      ("Sneaker clean", C.SHOES, I, 9000, 72, 1)],
     [("kagiso@demo.lc", 5, "Sneakers look brand new. Really impressed.", 35),
      ("lindiwe@demo.lc", 4, "Great prices for the quality.", 21),
      ("johan@demo.lc", 5, "Fast and friendly. The 24-hour option is a lifesaver.", 9),
      ("ayesha@demo.lc", 3, "Clothes were clean but one sock went missing in the folding.", 4)]),
    ("owner3@demo.lc", "David Naidoo", "Rosebank Dry Cleaners", "Rosebank", -26.1460, 28.0436,
     "Specialist dry cleaning for suits, dresses and delicate fabrics since 2009.", "cover-hangers.jpg",
     [("Suit dry clean", C.DRY_CLEANING, I, 13500, 72, 1), ("Dress dry clean", C.DRY_CLEANING, I, 9500, 72, 1),
      ("Shirt laundered & pressed", C.WASH_AND_IRON, I, 1800, 48, 1), ("Wedding dress", C.SPECIALITY, I, 85000, 168, 1),
      ("Curtains (per kg)", C.BEDDING, K, 6000, 96, 2)],
     [("johan@demo.lc", 5, "Best dry cleaner in Joburg. My suit looks tailor-new.", 50),
      ("ayesha@demo.lc", 5, "Handled my silk dress with real care.", 18),
      ("kagiso@demo.lc", 4, "Excellent work, a little pricey.", 6)]),
    ("owner4@demo.lc", "Zanele Mahlangu", "Maboneng Express Wash", "Maboneng", -26.2045, 28.0596,
     "Same-day laundry for busy people in the inner city. Ready in 24 hours.", "cover-iron.jpg",
     [("Same-day Wash & Fold", C.WASH_AND_FOLD, K, 2800, 24, 2), ("Wash & Iron", C.WASH_AND_IRON, K, 4000, 24, 2),
      ("Ironing only", C.IRONING, K, 2000, 24, 2), ("Sneaker clean", C.SHOES, I, 8000, 48, 1)],
     [("lindiwe@demo.lc", 4, "Quick turnaround, exactly as promised.", 14),
      ("kagiso@demo.lc", 5, "Use them every week. Never had a problem.", 3)]),
    ("owner5@demo.lc", "Themba Khoza", "Soweto Sparkle Laundry", "Orlando West", -26.2368, 27.9081,
     "Affordable family laundry. Big loads, blankets and school uniforms welcome.", "laundry-basket.jpg",
     [("Wash & Fold", C.WASH_AND_FOLD, K, 1800, 48, 4), ("Blanket wash", C.BEDDING, I, 11000, 72, 1),
      ("School uniform ironing", C.IRONING, I, 1000, 24, 3)],
     [("ayesha@demo.lc", 4, "Very affordable and friendly staff.", 28)]),
]

CUSTOMERS = [
    ("customer@demo.lc", "Thandi Mokoena", "+27821110001", "12 Pritchard St", "Marshalltown", -26.2041, 28.0473),
    ("lindiwe@demo.lc", "Lindiwe Zulu", "+27821110021", "8 Tyrone Ave", "Parkview", -26.1610, 28.0270),
    ("johan@demo.lc", "Johan Botha", "+27821110022", "31 4th Ave", "Melville", -26.1755, 28.0060),
    ("ayesha@demo.lc", "Ayesha Patel", "+27821110023", "15 Bath Ave", "Rosebank", -26.1450, 28.0410),
    ("kagiso@demo.lc", "Kagiso Molefe", "+27821110024", "77 Fox St", "Maboneng", -26.2050, 28.0580),
]


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
        user("admin2@demo.lc", "Lerato Admin", UserRole.ADMIN)
        user("admin3@demo.lc", "Sipho Admin", UserRole.ADMIN)

        for email, name, phone, street, suburb, lat, lng in CUSTOMERS:
            if c := user(email, name, UserRole.CUSTOMER, phone):
                c.customer_profile = CustomerProfile(address_line=street, suburb=suburb, city="Johannesburg",
                                                     latitude=lat, longitude=lng)
        db.flush()
        customers = {u.email: u for u in db.scalars(select(User).where(User.email.in_([c[0] for c in CUSTOMERS])))}

        for n, (email, owner_name, name, suburb, lat, lng, about, photo, services, reviews) in enumerate(LAUNDRIES):
            owner = user(email, owner_name, UserRole.BUSINESS, f"+2782111003{n}")
            if owner is None:
                continue
            biz = BusinessProfile(
                owner=owner, business_name=name, registration_number=f"2019/55512{n}/07", description=about,
                contact_phone=f"+2711333444{n}", address_line=f"{10 + n * 7} Main Rd", suburb=suburb,
                city="Johannesburg", province="Gauteng", latitude=lat, longitude=lng,
                verification_status=VerificationStatus.APPROVED, verified_at=now,
            )
            biz.staff.append(BusinessStaff(user=owner, staff_role=BusinessStaffRole.OWNER))
            for s_name, cat, unit, price, hours, minimum in services:
                biz.services.append(LaundryService(name=s_name, category=cat, pricing_unit=unit,
                                                   price_cents=price, turnaround_hours=hours, min_quantity=minimum))
            db.add(biz)
            db.flush()
            _add_photo(biz, photo, now)
            for customer_email, rating, comment, days_ago in reviews:
                _past_order_with_review(db, biz, customers[customer_email], rating, comment, now - timedelta(days=days_ago))
            if n == 0 and (att := user("attendant@demo.lc", "Lerato Dlamini", UserRole.BUSINESS)):
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

        # Waiting for approval, so the admin's verification queue has something in it
        if d := user("driver3@demo.lc", "Bongani Mthembu", UserRole.DRIVER, "+27821110013"):
            d.driver_profile = DriverProfile(id_number="P1000003", vehicle_type=VehicleType.BAKKIE,
                                             vehicle_registration="GP 345-678")
        if o := user("owner6@demo.lc", "Grace Mokoena", UserRole.BUSINESS, "+27821110036"):
            pending = BusinessProfile(
                owner=o, business_name="Sandton Steam Clean", registration_number="2024/555126/07",
                description="New premium laundry in Sandton.", contact_phone="+27113334446",
                address_line="5 Rivonia Rd", suburb="Sandton", city="Johannesburg", province="Gauteng",
                latitude=-26.1076, longitude=28.0567)
            pending.staff.append(BusinessStaff(user=o, staff_role=BusinessStaffRole.OWNER))
            db.add(pending)

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


def _add_photo(biz: BusinessProfile, filename: str, now: datetime) -> None:
    """Store a shop photo exactly like an owner's upload would (if the frontend
    folder is there; it isn't inside the production API container)."""
    path = PHOTOS / filename
    if not path.is_file():
        return
    data = covers.strip_metadata(path.read_bytes(), "image/jpeg")
    biz.cover_photo_path = storage.save(covers.FOLDER, f"{biz.id}.jpg", data)
    biz.cover_photo_type = "image/jpeg"
    biz.cover_photo_updated_at = now


def _past_order_with_review(db, biz: BusinessProfile, customer: User, rating: int, comment: str,
                            when: datetime) -> None:
    """A delivered order from the past, reviewed by the customer."""
    service = biz.services[0]
    qty = max(service.min_quantity, 4 if service.pricing_unit == PricingUnit.PER_KG else 2)
    subtotal, fee = service.price_cents * qty, 6000
    profile = customer.customer_profile
    address = dict(address_line=profile.address_line, suburb=profile.suburb, city=profile.city,
                   latitude=profile.latitude, longitude=profile.longitude)
    collect = when - timedelta(days=3)
    order = Order(
        order_number=new_order_number(), customer_id=customer.id, business_id=biz.id,
        status=OrderStatus.DELIVERED,
        **{f"collection_{k}": v for k, v in address.items()}, **{f"delivery_{k}": v for k, v in address.items()},
        collection_window_start=collect, collection_window_end=collect + timedelta(hours=2),
        delivery_window_start=when - timedelta(hours=2), delivery_window_end=when,
        subtotal_cents=subtotal, delivery_fee_cents=fee, total_cents=subtotal + fee, distance_km=4.0,
        is_estimate=False, paid_cents=subtotal + fee, created_at=collect - timedelta(hours=5),
    )
    db.add(order)
    db.flush()
    db.add(OrderItem(order_id=order.id, service_id=service.id, position=1, service_name=service.name,
                     category=service.category, pricing_unit=service.pricing_unit,
                     unit_price_cents=service.price_cents, turnaround_hours=service.turnaround_hours,
                     quantity=qty, line_total_cents=subtotal))
    db.add(Review(order_id=order.id, customer_id=customer.id, target=ReviewTarget.BUSINESS,
                  business_id=biz.id, rating=rating, comment=comment, created_at=when + timedelta(hours=3)))


if __name__ == "__main__":
    sys.exit(main())
