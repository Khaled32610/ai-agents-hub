"""
Validation Agent
=================
قواعد بسيطة فوق الـ Pydantic schema (اللي بتتأكد من نوع البيانات أصلًا)
عشان نتأكد إن الأرقام منطقية قبل التخزين. مطابق لمتطلبات السبك:
"Validates fields against rules (e.g., correct currency, mandatory fields)."
"""

from __future__ import annotations

from decimal import Decimal

from shared.logger import get_logger

from invoice_extraction.schemas import InvoiceExtraction, ValidationResult

log = get_logger("invoice_extraction.validation_agent")

TOLERANCE = Decimal("0.5")  # هامش خطأ مسموح به في حسابات التقريب

# قائمة عملات مقبولة - عدّل حسب احتياجك (ISO 4217، 3 حروف)
VALID_CURRENCIES = {"EGP", "USD", "EUR", "GBP", "SAR", "AED", "KWD"}

# الحقول الإلزامية زي ما مطلوب في السبك ("mandatory fields")
MANDATORY_FIELDS = ["vendor_name", "invoice_number", "invoice_date", "total_amount"]


def validate_invoice(invoice: InvoiceExtraction) -> ValidationResult:
    errors: list[str] = []

    # 1) mandatory fields - حسب نص السبك
    for field_name in MANDATORY_FIELDS:
        value = getattr(invoice, field_name, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"حقل إلزامي فارغ أو غير موجود: {field_name}")

    # 2) correct currency - حسب نص السبك
    # ملحوظة: currency بقت تتحول تلقائيًا لـ EGP لو مش موجودة (schemas.py)،
    # فهنا بس بنتأكد إنها من العملات المدعومة.
    warnings: list[str] = []
    if invoice.currency:
        currency_normalized = invoice.currency.strip().upper()
        if currency_normalized not in VALID_CURRENCIES:
            errors.append(f"currency غير معروفة أو غير مدعومة: {invoice.currency}")

    if invoice.total_amount is None or invoice.total_amount <= 0:
        errors.append("total_amount غير موجود أو أقل من أو يساوي صفر")

    if invoice.subtotal is not None and invoice.tax_amount is not None and invoice.total_amount is not None:
        expected_total = invoice.subtotal + invoice.tax_amount - (invoice.discount or Decimal("0"))
        if abs(expected_total - invoice.total_amount) > TOLERANCE:
            errors.append(
                f"total_amount ({invoice.total_amount}) لا يطابق subtotal+tax "
                f"({expected_total})"
            )

    if invoice.line_items:
        items_sum = sum((item.line_total or Decimal("0")) for item in invoice.line_items)
        reference = invoice.subtotal or invoice.total_amount
        if reference and abs(items_sum - reference) > TOLERANCE:
            errors.append(
                f"مجموع line_items ({items_sum}) لا يطابق subtotal/total ({reference})"
            )

    is_valid = len(errors) == 0
    if not is_valid:
        log.warning(f"فاتورة غير صالحة: {errors}")
    if warnings:
        log.info(f"تحذيرات فاتورة (مش رافضة): {warnings}")

    return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)