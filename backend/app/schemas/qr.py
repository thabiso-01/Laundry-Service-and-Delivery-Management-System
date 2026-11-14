import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import OrderStatus


class QrCodeOut(BaseModel):
    order_id: uuid.UUID
    order_number: str
    code: str  # the exact text encoded in the QR image


class ScanIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: str = Field(min_length=1, max_length=200)
    # Set when confirming a specific bag ("is this order X?") – a different
    # but valid code is then reported as a mismatch (SEC-012)
    expected_order_id: uuid.UUID | None = None


class ScanOut(BaseModel):
    valid: bool = True
    order_id: uuid.UUID
    order_number: str
    status: OrderStatus
    customer_name: str
    item_count: int
