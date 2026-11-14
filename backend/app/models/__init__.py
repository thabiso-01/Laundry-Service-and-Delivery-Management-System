# Import every model here so Alembic sees them all when generating migrations.
from app.models.audit import AuditLog
from app.models.catalog import LaundryService
from app.models.delivery import DeliveryJob, HandoverRecord, OrderOtp
from app.models.engagement import (
    DriverLocation,
    Notification,
    OrderAdjustment,
    Payment,
    PaymentEvent,
    Review,
)
from app.models.evidence import BagSeal, EvidencePhoto, Incident, IncidentUpdate
from app.models.orders import Order, OrderItem, OrderStatusEvent
from app.models.profiles import BusinessProfile, BusinessStaff, CustomerProfile, DriverProfile
from app.models.user import User
from app.models.verification import VerificationDocument

__all__ = [
    "AuditLog",
    "BagSeal",
    "EvidencePhoto",
    "Incident",
    "IncidentUpdate",
    "BusinessProfile",
    "BusinessStaff",
    "CustomerProfile",
    "DeliveryJob",
    "DriverLocation",
    "DriverProfile",
    "HandoverRecord",
    "LaundryService",
    "Notification",
    "Order",
    "OrderAdjustment",
    "OrderItem",
    "OrderOtp",
    "OrderStatusEvent",
    "Payment",
    "PaymentEvent",
    "Review",
    "User",
    "VerificationDocument",
]
