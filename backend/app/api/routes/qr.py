"""Order QR codes: show them, reissue them, and scan them (SEC-010 – SEC-012, UAT-008).

Every scan is written to the audit log – valid ones, forged or garbled ones,
and mismatches (a real code for the wrong bag or the wrong laundry).
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import CustomerUser, DbSession, require_business_staff
from app.api.routes.business_orders import _own_order as business_own_order
from app.api.routes.orders import _own_order as customer_own_order
from app.models import BusinessStaff, Order
from app.models.enums import BusinessStaffRole
from app.schemas.qr import QrCodeOut, ScanIn, ScanOut
from app.services import audit, qr

router = APIRouter(tags=["qr codes"])

Staff = Annotated[BusinessStaff, Depends(require_business_staff())]
Manager = Annotated[BusinessStaff, Depends(require_business_staff(BusinessStaffRole.MANAGER))]
Format = Annotated[Literal["png", "svg", "text"], Query(alias="format")]


def _qr_response(order: Order, fmt: str) -> Response | QrCodeOut:
    code = qr.code_for(order)
    if fmt == "text":
        return QrCodeOut(order_id=order.id, order_number=order.order_number, code=code)
    image, media_type = qr.render(code, fmt)
    return Response(
        content=image, media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{order.order_number}.{fmt}"',
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/api/orders/{order_id}/qr", response_model=None)
def customer_order_qr(
    order_id: uuid.UUID, customer: CustomerUser, db: DbSession, fmt: Format = "png"
) -> Response | QrCodeOut:
    """Your order's QR code – show it to the driver at collection."""
    return _qr_response(customer_own_order(db, customer, order_id), fmt)


@router.get("/api/business/orders/{order_id}/qr", response_model=None)
def business_order_qr(
    order_id: uuid.UUID, staff: Staff, db: DbSession, fmt: Format = "png"
) -> Response | QrCodeOut:
    """QR label to print and attach to the order's bag."""
    return _qr_response(business_own_order(db, staff, order_id), fmt)


@router.post("/api/business/orders/{order_id}/qr/reissue", response_model=QrCodeOut)
def reissue_order_qr(
    order_id: uuid.UUID, staff: Manager, db: DbSession, request: Request
) -> QrCodeOut:
    """Issue a new code when a label is lost, damaged or may have been copied.
    The old code stops working immediately."""
    order = business_own_order(db, staff, order_id, lock=True)
    order.qr_version += 1
    audit.record(db, "qr.reissued", actor_id=staff.user_id, entity_type="order",
                 entity_id=order.id,
                 details={"order_number": order.order_number, "version": order.qr_version},
                 request=request)
    db.commit()
    return QrCodeOut(order_id=order.id, order_number=order.order_number,
                     code=qr.code_for(order))


_MESSAGES = {
    qr.Problem.MALFORMED: "This is not a LaundryConnect order code",
    qr.Problem.BAD_SIGNATURE: "This code is not genuine – it may be forged or altered",
    qr.Problem.UNKNOWN_ORDER: "This code is not genuine – it may be forged or altered",
    qr.Problem.REPLACED: "This label has been replaced. Ask for the new label for this order",
}


@router.post("/api/scan", response_model=ScanOut)
def scan(body: ScanIn, staff: Staff, db: DbSession, request: Request) -> ScanOut:
    """Check a scanned order QR code (SEC-011, SEC-012)."""

    def reject(http_status: int, problem: str, message: str, order: Order | None = None):
        audit.record(
            db, "qr.scan_rejected", actor_id=staff.user_id,
            entity_type="order" if order else None, entity_id=order.id if order else None,
            details={"problem": problem, "code": body.code[:80],
                     "expected_order_id": str(body.expected_order_id)
                     if body.expected_order_id else None},
            request=request,
        )
        db.commit()
        raise HTTPException(http_status, {"valid": False, "problem": problem, "message": message})

    parsed = qr.parse(body.code)
    if isinstance(parsed, qr.Problem):
        reject(status.HTTP_422_UNPROCESSABLE_ENTITY, parsed.value, _MESSAGES[parsed])

    order = db.scalar(select(Order).where(Order.order_number == parsed.order_number))
    if order is None:
        reject(status.HTTP_422_UNPROCESSABLE_ENTITY, qr.Problem.UNKNOWN_ORDER.value,
               _MESSAGES[qr.Problem.UNKNOWN_ORDER])
    if parsed.version != order.qr_version:
        reject(status.HTTP_422_UNPROCESSABLE_ENTITY, qr.Problem.REPLACED.value,
               _MESSAGES[qr.Problem.REPLACED], order)
    if order.business_id != staff.business_id:
        # Real code, wrong laundry. Don't reveal anything about the order.
        reject(status.HTTP_409_CONFLICT, "wrong_business",
               "This bag belongs to a different laundry – do not accept it", order)
    if body.expected_order_id and body.expected_order_id != order.id:
        reject(status.HTTP_409_CONFLICT, "not_expected_order",
               f"Wrong bag: this is order {order.order_number}, not the one you selected", order)

    audit.record(db, "qr.scanned", actor_id=staff.user_id, entity_type="order",
                 entity_id=order.id, details={"order_number": order.order_number},
                 request=request)
    db.commit()
    return ScanOut(
        order_id=order.id, order_number=order.order_number, status=order.status,
        customer_name=order.customer.full_name, item_count=len(order.items),
    )
