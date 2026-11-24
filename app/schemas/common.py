from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import PlainSerializer, WithJsonSchema

TWO_DECIMAL_PLACES = Decimal("0.01")


def format_money(value: Decimal) -> str:
    """Định dạng Decimal thành chuỗi số thập phân cố định 2 chữ số sau dấu phẩy (ví dụ: '0.00')."""
    quantized = value.quantize(TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP)
    if quantized == Decimal("0.00"):
        quantized = Decimal("0.00")
    return str(quantized)


def format_utc_datetime(value: datetime) -> str:
    """Chuyển đổi datetime sang chuỗi chuẩn ISO 8601 ở múi giờ UTC (hậu tố 'Z')."""
    if value.tzinfo is None:
        utc_value = value.replace(tzinfo=timezone.utc)
    else:
        utc_value = value.astimezone(timezone.utc)
    return utc_value.isoformat().replace("+00:00", "Z")


MoneyDecimal = Annotated[
    Decimal,
    PlainSerializer(format_money, return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "example": "0.00",
            "pattern": r"^-?\d+\.\d{2}$",
        }
    ),
]

UTCDatetime = Annotated[
    datetime,
    PlainSerializer(format_utc_datetime, return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "format": "date-time",
            "example": "2026-11-18T10:00:00Z",
        }
    ),
]

__all__ = [
    "MoneyDecimal",
    "UTCDatetime",
    "format_money",
    "format_utc_datetime",
]
