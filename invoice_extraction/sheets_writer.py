"""Write invoice summary rows to a configured Google spreadsheet.

The service account uses the Sheets scope. Line items are stored separately in
Supabase. RAW writes keep untrusted document strings from becoming formulas.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from shared.config import settings
from shared.logger import get_logger

from invoice_extraction.schemas import InvoiceExtraction, ValidationResult

log = get_logger("invoice_extraction.sheets_writer")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Configure credentials and destination through local environment variables.
SERVICE_ACCOUNT_FILE = Path(settings.google_drive_credentials_json or "secrets/service-account.json")
if not SERVICE_ACCOUNT_FILE.is_absolute():
    SERVICE_ACCOUNT_FILE = Path(__file__).resolve().parent.parent / SERVICE_ACCOUNT_FILE
SPREADSHEET_ID = settings.google_sheet_id
SHEET_NAME = "Sheet1"
SHEET_RANGE = f"{SHEET_NAME}!A:T"  # 20 عمود A إلى T (بعد شيل line_items_json)
HEADER_RANGE = f"{SHEET_NAME}!A1:T1"

# ترتيب العناوين لازم يفضل متطابق حرفيًا مع ترتيب القيم في append_invoice_row
EXPECTED_HEADERS = [
    "invoice_id",
    "drive_file_id",
    "source_filename",
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "due_date",
    "customer_name",
    "customer_address",
    "customer_email",
    "customer_phone",
    "currency",
    "subtotal",
    "tax_amount",
    "discount",
    "total_amount",
    "total_due",
    "is_valid",
    "validation_errors",
    "created_at",
]


class SheetsWriteError(Exception):
    """Signals a Sheets failure; API processing continues with status reporting."""


def _get_service():
    if not SPREADSHEET_ID or not settings.google_drive_credentials_json:
        raise SheetsWriteError("Configure GOOGLE_SHEET_ID and GOOGLE_DRIVE_CREDENTIALS_JSON.")
    creds = Credentials.from_service_account_file(str(SERVICE_ACCOUNT_FILE), scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def ensure_headers(service=None) -> None:
    """
    يتأكد إن صف الـ headers (الصف الأول) مطابق لـ EXPECTED_HEADERS، ولو لأ بيصلحه.

    ليه محتاجينها: sheets_writer.py مبيكتبش header row تلقائيًا من الأساس،
    فلو حد عدّل الصف الأول يدويًا (مثلاً drag/autofill غلط في Google Sheets
    خلّى كل الأعمدة "invoice_id")، البيانات هتفضل بتتكتب صح تحت، بس
    العناوين هتبقى غلط ومحدش هيعرف عمود إيه بيمثل إيه.

    بتتنادى تلقائيًا قبل أول append، فمفيش داعي تشغّلها يدويًا في الوضع
    العادي - بس سيبتها متاحة لو حبيت تشغلها بنفسك أو من سكريبت صيانة.
    """
    service = service or _get_service()
    try:
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=SPREADSHEET_ID, range=HEADER_RANGE)
            .execute()
        )
        current = result.get("values", [[]])
        current_row = current[0] if current else []
    except HttpError as exc:
        log.warning(f"مقدرتش أقرا صف الـ headers الحالي، هكتب العناوين الصح فوق: {exc}")
        current_row = []

    if current_row == EXPECTED_HEADERS:
        return  # الهيدر سليم أصلاً، مفيش داعي نكتب

    log.warning(
        f"صف الـ headers في الشيت مش مطابق للمتوقع (القيمة الحالية: {current_row}) "
        f"- بيتصلح دلوقتي تلقائيًا."
    )
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=HEADER_RANGE,
        valueInputOption="RAW",
        body={"values": [EXPECTED_HEADERS]},
    ).execute()
    log.info("تم إصلاح صف الـ headers في Google Sheets.")


def append_invoice_row(
    invoice_id: str,
    drive_file_id: str | None,
    source_filename: str,
    invoice: InvoiceExtraction,
    validation: ValidationResult,
) -> None:
    """يضيف صف جديد في الشيت. بيرمي SheetsWriteError لو فشل، عشان الاستدعاء يقدر يعمل fallback."""
    row = [
        invoice_id,
        drive_file_id or "",
        source_filename,
        invoice.vendor_name or "",
        invoice.invoice_number or "",
        str(invoice.invoice_date) if invoice.invoice_date else "",
        str(invoice.due_date) if invoice.due_date else "",
        invoice.customer_name or "",
        invoice.customer_address or "",
        invoice.customer_email or "",
        invoice.customer_phone or "",
        invoice.currency or "",
        float(invoice.subtotal) if invoice.subtotal is not None else "",
        float(invoice.tax_amount) if invoice.tax_amount is not None else "",
        float(invoice.discount) if invoice.discount is not None else "",
        float(invoice.total_amount) if invoice.total_amount is not None else "",
        float(invoice.total_due) if invoice.total_due is not None else "",
        validation.is_valid,
        json.dumps(validation.errors, ensure_ascii=False),
        datetime.now(timezone.utc).isoformat(),
    ]

    try:
        service = _get_service()
        ensure_headers(service)
        service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=SHEET_RANGE,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        log.info(f"تم تسجيل الفاتورة {invoice_id} في Google Sheets")
    except (HttpError, FileNotFoundError, Exception) as exc:  # noqa: BLE001
        log.error(f"فشل الكتابة على Google Sheets للفاتورة {invoice_id}: {exc}")
        raise SheetsWriteError(str(exc)) from exc