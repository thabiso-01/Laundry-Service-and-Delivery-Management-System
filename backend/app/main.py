from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes import (
    admin,
    admin_incidents,
    auth,
    business,
    business_orders,
    documents,
    driver,
    geocode,
    incidents,
    laundries,
    notifications,
    orders,
    payments,
    photos,
    privacy,
    qr,
    reviews,
    staff,
    tracking,
)
from app.config import settings
from app.database import get_db

app = FastAPI(title=settings.app_name)
app.include_router(auth.router)
app.include_router(laundries.router)
app.include_router(geocode.router)
app.include_router(privacy.router)
app.include_router(orders.router)
app.include_router(documents.router)
app.include_router(business.router)
app.include_router(business_orders.router)
app.include_router(qr.router)
app.include_router(driver.router)
app.include_router(incidents.router)
app.include_router(photos.router)
app.include_router(admin_incidents.router)
app.include_router(payments.router)
app.include_router(notifications.router)
app.include_router(tracking.router)
app.include_router(tracking.admin)
app.include_router(reviews.router)
app.include_router(reviews.admin)
app.include_router(staff.router)
app.include_router(admin.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict:
    """Liveness check that also confirms the database is reachable."""
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "unreachable"
    return {"status": "ok", "database": db_status}
