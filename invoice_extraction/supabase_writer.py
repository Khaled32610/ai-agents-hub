"""
Supabase Writer
================
Supabase دلوقتي مخزن كامل موازي لـ Google Sheets (مش بس فحص تكرار):
نفس التفاصيل اللي بتتكتب في الشيت، **زائد** line_items (اللي اتشالت من
الشيت نفسه بعد شيل عمود line_items_json)، وده بيحل مشكلتين مرة واحدة:

1) فحص التكرار (نفس ملف اتعالج قبل كده بنفس الـ SHA256 hash) - كان شغّال
   على Postgres قبل كده.
2) تفاصيل بنود الفاتورة (line_items) اللي فقدناها لما شلنا عمود
   line_items_json من الشيت - دلوقتي محفوظة كـ JSON في Supabase بدل ما
   تتفقد خالص.

Google Sheets لسه بيتكتب فيه (سهل المراجعة/الفتح بسرعة من غير أي أداة)،
لكن Supabase دلوقتي هو الأساسي فعليًا للبيانات الكاملة + فحص التكرار،
مش مجرد سجل مساعد.

جدول Supabase المطلوب (شغّل database/supabase_schema.sql مرة واحدة):
    invoices (
        id uuid primary key,
        file_hash text unique not null,
        source_filename text, drive_file_id text,
        vendor_name text, invoice_number text, invoice_date date, due_date date,
        customer_name text, customer_address text, customer_email text, customer_phone text,
        currency text, subtotal numeric, tax_amount numeric, discount numeric,
        total_amount numeric, total_due numeric,
        line_items jsonb, is_valid boolean, validation_errors jsonb,
        sheets_synced boolean, created_at timestamptz
    )

الإعداد: SUPABASE_URL و SUPABASE_KEY في .env (Project Settings -> API
في لوحة تحكم Supabase - استخدم الـ service_role key من السيرفر، مش الـ
anon key، عشان الكتابة تنجح من غير قيود RLS).
"""

from __future__ import annotations

from functools import lru_cache

from supabase import create_client, Client

from shared.config import settings
from shared.logger import get_logger

from invoice_extraction.schemas import InvoiceExtraction, ValidationResult

log = get_logger("invoice_extraction.supabase_writer")

TABLE_NAME = "invoices"


class SupabaseNotConfigured(Exception):
    """بترفع لو SUPABASE_URL / SUPABASE_KEY مش موجودين في .env."""


class SupabaseWriteError(Exception):
    """بترفع لو فشل أي استدعاء لـ Supabase (شبكة، صلاحيات، إلخ)."""


@lru_cache(maxsize=1)
def _get_client() -> Client:
    if not settings.supabase_url or not settings.supabase_key:
        raise SupabaseNotConfigured(
            "SUPABASE_URL و/أو SUPABASE_KEY مش موجودين في .env - "
            "فحص التكرار والتخزين على Supabase مش هيشتغلوا من غيرهم."
        )
    return create_client(settings.supabase_url, settings.supabase_key)


def _decimal_to_float(value):
    return float(value) if value is not None else None


def is_duplicate(file_hash: str) -> bool:
    """
    يتشيك هل الملف اتعالج قبل كده (SHA256)، زي is_duplicate القديمة في
    storage_writer.py بتاع Postgres.

    لو Supabase مش متظبط (.env ناقص)، بيرجع False (يعني "كمّل عادي") بدل
    ما يفشل الطلب كله - فحص التكرار وقتها بيبقى معطّل مؤقتًا لحد ما تتظبط
    المفاتيح، وده أرحم من رفض كل الفواتير أو تعليق الـ pipeline بالكامل.
    """
    try:
        client = _get_client()
    except SupabaseNotConfigured as exc:
        log.warning(f"فحص التكرار متعطّل مؤقتًا: {exc}")
        return False

    try:
        result = (
            client.table(TABLE_NAME)
            .select("id")
            .eq("file_hash", file_hash)
            .limit(1)
            .execute()
        )
        return len(result.data or []) > 0
    except Exception as exc:  # noqa: BLE001
        log.error(f"فشل فحص التكرار في Supabase (هنكمّل من غير فحص): {exc}")
        return False


def save_invoice_record(
    invoice_id: str,
    file_hash: str,
    source_filename: str,
    drive_file_id: str | None,
    invoice: InvoiceExtraction,
    validation: ValidationResult,
    sheets_synced: bool,
) -> None:
    """
    يخزن نسخة كاملة من الفاتورة في Supabase (نفس أعمدة الشيت + line_items)،
    وبرضو بيسجلها عشان is_duplicate() تلاقيها المرة الجاية.

    بيرمي SupabaseWriteError لو فشل - api.py بيمسكها ويكمل عادي (زي التعامل
    مع SheetsWriteError بالظبط)، عشان فشل الكتابة هنا ميوقفش الرد للمستخدم.
    """
    try:
        client = _get_client()
    except SupabaseNotConfigured as exc:
        log.warning(f"مش هينسجل في Supabase: {exc}")
        return

    row = {
        "id": invoice_id,
        "file_hash": file_hash,
        "source_filename": source_filename,
        "drive_file_id": drive_file_id,
        "vendor_name": invoice.vendor_name,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else None,
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "customer_name": invoice.customer_name,
        "customer_address": invoice.customer_address,
        "customer_email": invoice.customer_email,
        "customer_phone": invoice.customer_phone,
        "currency": invoice.currency,
        "subtotal": _decimal_to_float(invoice.subtotal),
        "tax_amount": _decimal_to_float(invoice.tax_amount),
        "discount": _decimal_to_float(invoice.discount),
        "total_amount": _decimal_to_float(invoice.total_amount),
        "total_due": _decimal_to_float(invoice.total_due),
        "line_items": [item.model_dump(mode="json") for item in invoice.line_items],
        "is_valid": validation.is_valid,
        "validation_errors": validation.errors,
        "sheets_synced": sheets_synced,
    }

    try:
        client.table(TABLE_NAME).insert(row).execute()
        log.info(f"تم تسجيل الفاتورة {invoice_id} كاملة في Supabase (hash={file_hash[:12]}...)")
    except Exception as exc:  # noqa: BLE001
        log.error(f"فشل تسجيل الفاتورة {invoice_id} في Supabase: {exc}")
        raise SupabaseWriteError(str(exc)) from exc