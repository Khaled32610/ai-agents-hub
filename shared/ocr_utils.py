"""
OCR & PDF Utilities (Shared)
=============================
دوال مشتركة يستخدمها Pipeline الفواتير أساسًا، لكن مبنية بشكل عام
عشان أي pipeline تاني يحتاج يقرأ PDF/صور يقدر يستخدمها.

الاستراتيجية:
1. نحاول استخراج نص مباشر من الـ PDF (PyMuPDF) لو الملف نصي أصلًا (أسرع وأدق).
2. لو النص طلع فاضي/قليل جدًا (يعني سكان/صورة) → نعمل OCR بالـ Tesseract.

ملاحظة عن الفواتير العربية:
- Tesseract بيرجّع الأرقام زي ما هي مكتوبة في الصورة، فلو الفاتورة مكتوبة
  بالأرقام الهندية (١٢٣٤٥) أو الفارسية (۱۲۳۴۵) بيرجعها زي ما هي، وده بيلخبط
  أي parsing رقمي لاحق. عشان كده بنعمل تطبيع (normalize) لكل نص طالع من OCR
  يحوّل الأرقام دي لأرقام غربية عادية (0-9) قبل ما نرجّعه.
- ضفنا `--psm 6` كـ default لـ Tesseract config، وده بيفترض إن الصفحة "بلوك
  نص متجانس واحد" بدل الوضع الافتراضي (auto page segmentation) اللي بيميل
  يلخبط ترتيب أعمدة الجداول مع نص RTL. لو عندك فواتير شكلها جدول واضح جدًا
  ممكن تجرب `--psm 4` بدل كده وتقارن الدقة.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf as fitz  # PyMuPDF (الاسم الجديد الموصى به بدل `import fitz`)
import pytesseract
from PIL import Image

from shared.config import settings
from shared.logger import get_logger

log = get_logger("ocr_utils")

MIN_TEXT_LENGTH_THRESHOLD = 30  # لو أقل من كده، نعتبره سكان محتاج OCR

# إعدادات Tesseract الافتراضية: psm 6 = "افترض بلوك نص متجانس واحد"،
# بيقلل تخبيط ترتيب الأعمدة في فواتير عربية شكلها جدول مقارنة بالـ auto mode.
TESSERACT_CONFIG = "--psm 6"

# تحويل الأرقام العربية الهندية (Arabic-Indic) والفارسية (Extended Arabic-Indic)
# للأرقام الغربية العادية 0-9، عشان أي مبلغ/تاريخ/رقم فاتورة يبقى قابل للـ parsing.
_DIGIT_TRANSLATION_TABLE = str.maketrans(
    "٠١٢٣٤٥٦٧٨٩" "۰۱۲۳۴۵۶۷۸۹",
    "01234567890123456789",
)


def _normalize_digits(text: str) -> str:
    """يحوّل أي أرقام عربية/فارسية موجودة في النص لأرقام غربية 0-9."""
    return text.translate(_DIGIT_TRANSLATION_TABLE)


@dataclass
class ExtractedDocument:
    text: str
    engine: str  # "pymupdf" | "tesseract"
    page_count: int
    file_hash: str


def compute_file_hash(file_path: str | Path) -> str:
    """SHA256 لمنع تكرار معالجة نفس الملف مرتين."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def extract_text_from_pdf(file_path: str | Path) -> ExtractedDocument:
    """
    يفتح PDF ويحاول ياخد النص مباشرة. لو مفيش نص كافي (يعني سكان)،
    يرجّع صفحات كـ صور ويعمل عليها Tesseract.
    """
    file_path = Path(file_path)
    file_hash = compute_file_hash(file_path)

    with fitz.open(file_path) as doc:
        if doc.page_count > 20:
            raise ValueError("Maximum 20 PDF pages")
        direct_text_parts: list[str] = []
        for page in doc:
            direct_text_parts.append(page.get_text())
        direct_text = "\n".join(direct_text_parts).strip()

        if len(direct_text) >= MIN_TEXT_LENGTH_THRESHOLD:
            direct_text = _normalize_digits(direct_text)
            log.info(f"استخراج نص مباشر (PyMuPDF) من {file_path.name} - {len(direct_text)} حرف")
            return ExtractedDocument(
                text=direct_text,
                engine="pymupdf",
                page_count=doc.page_count,
                file_hash=file_hash,
            )

        log.info(f"النص المباشر قليل جدًا في {file_path.name}، هنعمل OCR بالـ Tesseract")
        ocr_text_parts: list[str] = []
        for page_index in range(doc.page_count):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(dpi=300)  # دقة عالية لتحسين دقة الـ OCR
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            page_text = pytesseract.image_to_string(
                img, lang=settings.tesseract_lang, config=TESSERACT_CONFIG
            )
            ocr_text_parts.append(page_text)

        ocr_text = _normalize_digits("\n".join(ocr_text_parts).strip())
        return ExtractedDocument(
            text=ocr_text,
            engine="tesseract",
            page_count=doc.page_count,
            file_hash=file_hash,
        )

def extract_text_from_image(file_path: str | Path) -> ExtractedDocument:
    """OCR مباشر لصورة (jpg/png) بدل PDF."""
    file_path = Path(file_path)
    file_hash = compute_file_hash(file_path)

    with Image.open(file_path) as img:
        text = pytesseract.image_to_string(
            img, lang=settings.tesseract_lang, config=TESSERACT_CONFIG
        )
    text = _normalize_digits(text.strip())

    return ExtractedDocument(
        text=text,
        engine="tesseract",
        page_count=1,
        file_hash=file_hash,
    )
