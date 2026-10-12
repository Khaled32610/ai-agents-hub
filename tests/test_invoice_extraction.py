"""
اختبارات أساسية لـ Pipeline الفواتير.
معظمها unit tests بتستخدم mocking بدل استدعاء APIs حقيقية (توفير تكلفة).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from invoice_extraction.schemas import InvoiceExtraction, LineItem
from invoice_extraction.validation_agent import validate_invoice


def make_invoice(**overrides) -> InvoiceExtraction:
    defaults = dict(
        vendor_name="شركة الاختبار",
        invoice_number="INV-001",
        invoice_date="2026-01-01",
        currency="EGP",
        subtotal=Decimal("100.00"),
        tax_amount=Decimal("14.00"),
        total_amount=Decimal("114.00"),
        line_items=[LineItem(description="خدمة تجريبية", quantity=1, unit_price=Decimal("100.00"), line_total=Decimal("100.00"))],
    )
    defaults.update(overrides)
    return InvoiceExtraction(**defaults)


def test_valid_invoice_passes_validation():
    invoice = make_invoice()
    result = validate_invoice(invoice)
    assert result.is_valid is True
    assert result.errors == []


def test_mismatched_total_fails_validation():
    invoice = make_invoice(total_amount=Decimal("999.00"))
    result = validate_invoice(invoice)
    assert result.is_valid is False
    assert any("total_amount" in e for e in result.errors)


def test_zero_total_fails_validation():
    invoice = make_invoice(total_amount=Decimal("0"))
    result = validate_invoice(invoice)
    assert result.is_valid is False


def test_empty_vendor_name_fails_validation():
    invoice = make_invoice(vendor_name="  ")
    result = validate_invoice(invoice)
    assert result.is_valid is False
    assert any("vendor_name" in e for e in result.errors)


@patch("invoice_extraction.extractor_agent.generate_structured")
def test_extraction_retries_and_returns_best_result(generate):
    from invoice_extraction.extractor_agent import extract_invoice_data
    incomplete = make_invoice(invoice_number=None)
    complete = make_invoice()
    generate.side_effect = [incomplete, complete]
    assert extract_invoice_data("Synthetic invoice") == complete
    assert generate.call_count == 2


def test_line_total_computed_when_omitted():
    item = LineItem(description="Synthetic", quantity=2, unit_price=Decimal("5"))
    assert item.line_total == Decimal("10")
