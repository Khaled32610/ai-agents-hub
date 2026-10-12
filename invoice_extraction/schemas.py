"""Pydantic Schemas - الشكل المتوقع من الـ LLM Extraction Agent."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# لو الـ LLM رجّع تاريخ مع وقت ("2026-09-05 16:49" أو "2026-09-05T16:49:00")
# بنشيل جزء الوقت ونسيب التاريخ بس، بدل ما نرفضه بالكامل.
_DATETIME_TRIM_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T]\d{2}:\d{2}(:\d{2})?")


def _strip_time_component(value):
    if isinstance(value, str):
        match = _DATETIME_TRIM_RE.match(value.strip())
        if match:
            return match.group(1)
    return value


class LineItem(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: Decimal = Decimal("0")
    line_total: Decimal | None = Field(default=None, validate_default=True)

    @field_validator("line_total")
    @classmethod
    def compute_total_if_missing(cls, v, info):
        if v is not None:
            return v
        qty = info.data.get("quantity", 1.0)
        price = info.data.get("unit_price", Decimal("0"))
        return Decimal(str(qty)) * price


class InvoiceExtraction(BaseModel):
    """الشكل اللي المفروض الـ LLM يرجعه كـ JSON."""

    vendor_name: str = Field(
        ..., description="اسم المورد/المحل صاحب الفاتورة — مش اسم العميل"
    )
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None

    @field_validator("invoice_date", "due_date", mode="before")
    @classmethod
    def _trim_time_from_date(cls, v):
        return _strip_time_component(v)

    customer_name: str | None = Field(
        default=None, description="اسم الشخص أو الجهة المشترية — مش اسم المورد"
    )
    customer_address: str | None = None
    customer_email: str | None = None
    customer_phone: str | None = None

    currency: str | None = None
    subtotal: Decimal | None = None
    tax_amount: Decimal | None = None
    discount: Decimal | None = None
    total_amount: Decimal | None = Field(
        default=None,
        description="الإجمالي النهائي المطبوع في الفاتورة بعد الضريبة والخصم (الرقم الأهم)",
    )
    total_due: Decimal | None = Field(
        default=None,
        description="يتحط بس لو فيه فرق فعلي بين إجمالي الفاتورة والمبلغ المطلوب دفعه دلوقتي",
    )
    line_items: list[LineItem] = Field(default_factory=list)

    model_config = ConfigDict()

    @model_validator(mode="after")
    def _default_currency_egp(self):
        # لو الفاتورة ما فيهاش عملة مكتوبة صراحةً، بنفترض جنيه مصري افتراضيًا.
        # model_validator (بعكس field_validator) بيشتغل دايمًا حتى لو currency
        # فضلت على قيمتها الافتراضية (None) ومتبعتش صراحةً.
        if self.currency is None or not self.currency.strip():
            self.currency = "EGP"
        return self


class ValidationResult(BaseModel):
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)