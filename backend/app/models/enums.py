from enum import StrEnum


class UserRole(StrEnum):
    """SEC-018: the four platform roles."""

    CUSTOMER = "customer"
    DRIVER = "driver"
    BUSINESS = "business"
    ADMIN = "admin"


class AccountStatus(StrEnum):
    """Whether a user may log in at all (SEC-044: suspension)."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class VerificationStatus(StrEnum):
    """Admin review state for drivers, businesses and documents (UR-004)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class BusinessStaffRole(StrEnum):
    """A person's job inside one laundry business (SEC-011, SEC-017).

    OWNER     – full control, manages staff; the account that registered the business
    MANAGER   – manages orders, services and attendants, but not owners/managers
    ATTENDANT – front-counter / floor staff: scan QR codes, verify seals,
                record handovers, update order status
    """

    OWNER = "owner"
    MANAGER = "manager"
    ATTENDANT = "attendant"


class ServiceCategory(StrEnum):
    """Groups services so customers can compare like with like (UR-006)."""

    WASH_AND_FOLD = "wash_and_fold"
    WASH_AND_IRON = "wash_and_iron"
    IRONING = "ironing"
    DRY_CLEANING = "dry_cleaning"
    BEDDING = "bedding"  # duvets, blankets, curtains
    SHOES = "shoes"
    SPECIALITY = "speciality"  # wedding dresses, leather, suits
    OTHER = "other"


class PricingUnit(StrEnum):
    PER_KG = "per_kg"
    PER_ITEM = "per_item"
    PER_LOAD = "per_load"


class OrderStatus(StrEnum):
    """The whole order lifecycle (UR-011, UR-012). Later steps add the
    transitions for businesses and drivers.

    placed → accepted → collected → received → processing → ready
           → out_for_delivery → delivered
    placed → declined            (business can't take it)
    placed/accepted → cancelled  (customer, before collection)
    """

    PLACED = "placed"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    COLLECTED = "collected"            # driver has the laundry (SEC-013)
    RECEIVED = "received"              # laundry business has it (SEC-014)
    PROCESSING = "processing"
    READY = "ready"
    OUT_FOR_DELIVERY = "out_for_delivery"  # handed to driver (SEC-015)
    DELIVERED = "delivered"            # back with the customer (SEC-016)


class JobKind(StrEnum):
    COLLECTION = "collection"  # customer → laundry
    DELIVERY = "delivery"      # laundry → customer


class JobStatus(StrEnum):
    OPEN = "open"            # on the job board
    ASSIGNED = "assigned"    # a driver accepted it
    PICKED_UP = "picked_up"  # driver has the bag
    COMPLETED = "completed"  # bag handed over at the destination
    CANCELLED = "cancelled"


class OtpPurpose(StrEnum):
    COLLECTION = "collection"  # SEC-005
    DELIVERY = "delivery"      # SEC-006


class HandoverKind(StrEnum):
    """The four handovers of every order (SEC-013 – SEC-016)."""

    CUSTOMER_TO_DRIVER = "customer_to_driver"
    DRIVER_TO_BUSINESS = "driver_to_business"
    BUSINESS_TO_DRIVER = "business_to_driver"
    DRIVER_TO_CUSTOMER = "driver_to_customer"


class HandoverMethod(StrEnum):
    OTP = "otp"
    QR = "qr"


class SealCheck(StrEnum):
    """Result of checking a tamper-evident seal at the end of a trip (SEC-027)."""

    INTACT = "intact"
    BROKEN = "broken"
    MISSING = "missing"


class PhotoStage(StrEnum):
    COLLECTION = "collection"  # driver at the customer (SEC-029)
    RECEIPT = "receipt"        # laundry receiving the bag (SEC-030)
    PICKUP = "pickup"          # driver collecting clean laundry
    DELIVERY = "delivery"      # driver at final delivery (SEC-031)
    INCIDENT = "incident"      # evidence attached to a report


class IncidentCategory(StrEnum):
    MISSING_ITEMS = "missing_items"      # SEC-033
    DAMAGED_ITEMS = "damaged_items"
    WRONG_ITEMS = "wrong_items"
    BROKEN_SEAL = "broken_seal"          # SEC-028
    SEAL_MISMATCH = "seal_mismatch"
    LATE_OR_NO_SHOW = "late_or_no_show"
    CONDUCT = "conduct"                  # rude, unsafe or inappropriate behaviour
    FRAUD = "fraud"                      # SEC-048
    SECURITY = "security"                # SEC-034
    OTHER = "other"


class IncidentStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class IncidentSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"  # replaced by a newer checkout


class ReviewTarget(StrEnum):
    BUSINESS = "business"
    DRIVER = "driver"


class DocumentType(StrEnum):
    # Drivers (SEC-001, SEC-002)
    NATIONAL_ID = "national_id"
    PASSPORT = "passport"
    DRIVERS_LICENCE = "drivers_licence"
    SELFIE = "selfie"
    PROFILE_PHOTO = "profile_photo"
    VEHICLE_REGISTRATION = "vehicle_registration"
    # Businesses (SEC-043)
    BUSINESS_REGISTRATION = "business_registration"  # CIPC certificate
    PROOF_OF_ADDRESS = "proof_of_address"
    TAX_CLEARANCE = "tax_clearance"
    OTHER = "other"


class VehicleType(StrEnum):
    CAR = "car"
    BAKKIE = "bakkie"
    VAN = "van"
    MOTORCYCLE = "motorcycle"
    BICYCLE = "bicycle"
