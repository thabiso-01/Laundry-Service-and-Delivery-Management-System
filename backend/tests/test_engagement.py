"""Notifications (UR-016), live tracking (SEC-021 – SEC-024, UAT-010) and
ratings & reviews (UR-014)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, DriverLocation, Notification
from app.models.enums import JobKind, UserRole
from tests.conftest import auth_header
from tests.test_driver_flow import (  # noqa: F401 (fixtures are used by name)
    AT_HOME,
    AT_LAUNDRY,
    accepted_order,
    collect,
    customer,
    customer_code,
    driver,
    job_of,
    laundry,
    make_ready,
    new_seal,
    online_driver,
    qr_code,
    receive,
    take,
)

MIDRAND = {"latitude": -25.9992, "longitude": 28.1263}  # far north of the JHB route


def ping(client, driver, job, where):
    return client.post(f"/api/driver/jobs/{job.id}/location", headers=auth_header(driver),
                       json=where)


@pytest.fixture
def delivered(client, db, customer, laundry, online_driver, accepted_order):
    """An order taken all the way to the customer, by two different drivers."""
    o = accepted_order
    collector, deliverer = online_driver(), online_driver()
    job = job_of(db, o, JobKind.COLLECTION)
    take(client, collector, job)
    collect(client, collector, job, customer_code(client, customer, o))
    receive(client, laundry, o, qr_code(client, laundry, o))
    make_ready(client, laundry, o)
    delivery = job_of(db, o, JobKind.DELIVERY)
    take(client, deliverer, delivery)
    client.post(f"/api/driver/jobs/{delivery.id}/pickup", headers=auth_header(deliverer),
                json={"code": qr_code(client, laundry, o), "seal_numbers": [new_seal()],
                      **AT_LAUNDRY})
    r = client.post(f"/api/driver/jobs/{delivery.id}/deliver", headers=auth_header(deliverer),
                    json={"otp": customer_code(client, customer, o), "seals_intact": True,
                          **AT_HOME})
    assert r.status_code == 200, r.text
    return {"order": o, "collection": job, "delivery": delivery,
            "collector": collector, "deliverer": deliverer}


# ======================= Notifications =======================

def test_customer_is_kept_informed_through_the_journey(client, db, customer, delivered):
    inbox = client.get("/api/notifications", headers=auth_header(customer)).json()
    kinds = [n["kind"] for n in reversed(inbox["items"])]
    for expected in ("payment.received", "order.accepted", "driver.assigned", "order.collected",
                     "order.received", "order.ready", "order.out_for_delivery",
                     "order.delivered"):
        assert expected in kinds, expected
    assert inbox["unread"] == len(inbox["items"])


def test_notifications_never_contain_one_time_codes(client, db, customer, laundry,
                                                    online_driver, accepted_order):
    code = customer_code(client, customer, accepted_order)
    bodies = db.scalars(select(Notification.body).where(Notification.user_id == customer.id))
    assert all(code not in b for b in bodies)


def test_mark_read_and_read_all(client, customer, make_user, delivered):
    h = auth_header(customer)
    first = client.get("/api/notifications", headers=h).json()["items"][0]
    r = client.post(f"/api/notifications/{first['id']}/read", headers=h)
    assert r.json()["read_at"] is not None
    stranger = make_user(UserRole.CUSTOMER)
    assert client.post(f"/api/notifications/{first['id']}/read",
                       headers=auth_header(stranger)).status_code == 404
    client.post("/api/notifications/read-all", headers=h)
    assert client.get("/api/notifications?unread_only=true", headers=h).json() == {
        "items": [], "unread": 0}


def test_business_hears_about_new_paid_orders_and_cancellations(client, db, customer, laundry,
                                                                accepted_order):
    client.post(f"/api/orders/{accepted_order['id']}/cancel", headers=auth_header(customer))
    kinds = db.scalars(select(Notification.kind).where(
        Notification.user_id == laundry.owner.id)).all()
    assert "order.new" in kinds and "order.cancelled" in kinds


# ======================= Tracking =======================

def test_customer_sees_driver_on_the_way(client, db, customer, driver, accepted_order):
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    h = auth_header(customer)
    before = client.get(f"/api/orders/{accepted_order['id']}/tracking", headers=h).json()
    assert before["latitude"] is None and before["is_live"] is False

    assert ping(client, driver, job, AT_LAUNDRY).json() == {"accepted": True, "off_route": False}
    assert ping(client, driver, job, AT_HOME).json()["accepted"] is False  # too soon

    now = client.get(f"/api/orders/{accepted_order['id']}/tracking", headers=h).json()
    assert now["is_live"] is True
    assert now["latitude"] == AT_LAUNDRY["latitude"]
    assert now["driver_first_name"] == "Sipho"
    assert 1 < now["distance_to_destination_km"] < 4  # laundry → customer's home


def test_no_tracking_without_an_active_trip(client, customer, laundry, delivered):
    r = client.get(f"/api/orders/{delivered['order']['id']}/tracking",
                   headers=auth_header(customer))
    assert r.status_code == 404


def test_old_positions_are_not_live(client, db, customer, driver, accepted_order):
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    ping(client, driver, job, AT_LAUNDRY)
    loc = db.scalar(select(DriverLocation).where(DriverLocation.job_id == job.id))
    loc.recorded_at = datetime.now(UTC) - timedelta(minutes=30)
    db.flush()
    r = client.get(f"/api/orders/{accepted_order['id']}/tracking", headers=auth_header(customer))
    assert r.json()["is_live"] is False


def test_only_the_assigned_driver_can_send_positions(client, db, online_driver, accepted_order):
    owner, other = online_driver(), online_driver()
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, owner, job)
    assert ping(client, other, job, AT_HOME).status_code == 404


def test_route_deviation_flagged_for_admins(client, db, customer, driver, make_user,
                                            accepted_order):
    admin = make_user(UserRole.ADMIN)
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    collect(client, driver, job, customer_code(client, customer, accepted_order))
    # Carrying the laundry, the driver heads to Midrand instead of the laundry
    r = ping(client, driver, job, MIDRAND)
    assert r.json()["off_route"] is True
    assert db.scalar(select(AuditLog).where(AuditLog.action == "job.route_deviation"))

    deviations = client.get("/api/admin/route-deviations", headers=auth_header(admin)).json()
    assert [d["order_number"] for d in deviations] == [accepted_order["order_number"]]
    route = client.get(f"/api/admin/orders/{accepted_order['id']}/route",
                       headers=auth_header(admin)).json()
    assert route[0]["off_route_points"] == 1
    assert client.get("/api/admin/route-deviations",
                      headers=auth_header(customer)).status_code == 403


def test_waiting_at_pickup_is_not_off_route(client, db, driver, accepted_order):
    # Before collection the driver can be anywhere on the way to the customer
    job = job_of(db, accepted_order, JobKind.COLLECTION)
    take(client, driver, job)
    assert ping(client, driver, job, MIDRAND).json()["off_route"] is False


# ======================= Reviews =======================

def review(client, customer, order, **body):
    return client.post(f"/api/orders/{order['id']}/reviews", headers=auth_header(customer),
                       json=body)


def test_customer_rates_laundry_and_both_drivers(client, db, customer, laundry, delivered):
    o = delivered["order"]
    assert review(client, customer, o, target="business", rating=4,
                  comment="Shirts came back crisp").status_code == 201
    assert review(client, customer, o, target="driver", job_id=str(delivered["collection"].id),
                  rating=5).status_code == 201
    assert review(client, customer, o, target="driver", job_id=str(delivered["delivery"].id),
                  rating=3).status_code == 201

    # Shown publicly with the reviewer's first name only
    public = client.get(f"/api/laundries/{laundry.id}/reviews").json()
    assert public[0]["reviewer"] == customer.full_name.split()[0]
    assert public[0]["comment"] == "Shirts came back crisp"

    page = client.get(f"/api/laundries/{laundry.id}").json()
    assert (page["rating_avg"], page["rating_count"]) == (4.0, 1)
    ratings = client.get("/api/driver/ratings", headers=auth_header(delivered["deliverer"])).json()
    assert (ratings["rating_avg"], ratings["rating_count"]) == (3.0, 1)


def test_review_rules(client, customer, make_user, laundry, delivered, accepted_order):
    o = delivered["order"]
    assert review(client, customer, o, target="business", rating=6).status_code == 422
    assert review(client, customer, o, target="business", rating=5).status_code == 201
    assert review(client, customer, o, target="business", rating=1).status_code == 409  # twice
    assert review(client, customer, o, target="driver", rating=5).status_code == 422  # no job
    stranger = make_user(UserRole.CUSTOMER)
    assert review(client, stranger, o, target="business", rating=1).status_code == 404


def test_cannot_review_before_delivery(client, db, customer, laundry, make_user):
    from tests.test_orders import order_body, place
    o = place(client, customer, order_body(laundry)).json()
    assert review(client, customer, o, target="business", rating=5).status_code == 409


def test_search_sorts_by_rating(client, customer, laundry, make_laundry, delivered):
    unrated = make_laundry(-26.1950, 28.0320)
    unrated.business_name = "New Laundry"
    review(client, customer, delivered["order"], target="business", rating=5)
    r = client.get("/api/laundries", params={"lat": AT_HOME["latitude"],
                                             "lng": AT_HOME["longitude"], "sort": "rating"})
    items = r.json()["items"]
    assert items[0]["id"] == str(laundry.id) and items[0]["rating_avg"] == 5.0
    assert items[-1]["rating_count"] == 0


def test_admin_hides_abusive_review(client, customer, laundry, make_user, delivered):
    admin = make_user(UserRole.ADMIN)
    rid = review(client, customer, delivered["order"], target="business", rating=1,
                 comment="(abusive text)").json()["id"]
    r = client.post(f"/api/admin/reviews/{rid}/hide", headers=auth_header(admin),
                    json={"reason": "Abusive language"})
    assert r.json() == {"rating_avg": None, "rating_count": 0}
    assert client.get(f"/api/laundries/{laundry.id}/reviews").json() == []
