"""
PDF Processor
==============
طبقة رفيعة فوق shared/ocr_utils مخصوصة لسياق الفواتير:
بتاخد مسار الملف وترجع نص جاهز للـ LLM Extraction Agent + الـ hash لمنع التكرار.
"""

from __future__ import annotations

from pathlib import Path

from shared.logger import get_logger
from shared.ocr_utils import ExtractedDocument, extract_text_from_image, extract_text_from_pdf

log = get_logger("invoice_extraction.pdf_processor")

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def process_invoice_file(file_path: str | Path) -> ExtractedDocument:
    """
    نقطة الدخول الوحيدة اللي باقي كود invoice_extraction بيستخدمها.
    بتتعامل مع PDF أو صورة، وترجع نفس الشكل (ExtractedDocument).
    """
    file_path = Path(file_path)
    log.info(f"معالجة الملف: {file_path.name}")

    if file_path.suffix.lower() == ".pdf":
        return extract_text_from_pdf(file_path)
    elif file_path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
        return extract_text_from_image(file_path)
    else:
        raise ValueError(f"صيغة ملف غير مدعومة: {file_path.suffix}")
