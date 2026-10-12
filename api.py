"""
FastAPI Wrapper
================
بيلف الـ pipelines (فواتير + بحث) بـ HTTP endpoints بسيطة عشان n8n
يناديها بدل ما ينفذ سكريبتات بايثون مباشرة. نفس منطق run_invoice_pipeline.py
و run_research_pipeline.py بالظبط، غيّرنا بس نقطة الدخول من CLI لـ HTTP.

تشغيل محلي:
    uvicorn api:app --reload --port 8000

الاستخدام:
    POST /invoices/process   (multipart/form-data, حقل "file")
    POST /research/run       (JSON: {"query": "...", "max_results": 5})
    GET  /health

ملاحظة على التخزين:
    Supabase هو المصدر الكامل لبيانات الفاتورة دلوقتي (كل الحقول + line_items
    كـ JSON)، وهو نفسه اللي بيتسجل فيه فحص التكرار. Google Sheets لسه بيتكتب
    فيه بالتوازي كنسخة قابلة للقراءة السريعة (من غير عمود line_items، عشان
    يفضل الشيت مرتب). لو أي كتابة فشلت (Sheets أو Supabase)، الطلب مش بيفشل
    بالكامل - بيترجع الحالة في الرد (sheets_synced) وبيتسجل تحذير في اللوج.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

import pymupdf as fitz
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from shared.logger import get_logger
from shared.ocr_utils import compute_file_hash
from shared.lang_utils import detect_query_language

from invoice_extraction.extractor_agent import (
    extract_invoice_data,
    extract_invoice_data_from_images,
)
from invoice_extraction.pdf_processor import process_invoice_file
from invoice_extraction.sheets_writer import append_invoice_row, SheetsWriteError
from invoice_extraction.supabase_writer import (
    is_duplicate,
    save_invoice_record,
    SupabaseWriteError,
)
from invoice_extraction.validation_agent import validate_invoice

from web_research.browser_agent import fetch_multiple_pages
from web_research.report_exporter import (
    REPORTS_DIR,
    save_html_report,
    save_markdown_report,
    save_pdf_report,
)
from web_research.search_agent import search_topic
from web_research.summarizer_agent import summarize_multiple, generate_final_report

log = get_logger("api")

app = FastAPI(
    title="AI Agents Hub API",
    description="واجهة HTTP للـ pipelines عشان n8n ينادي عليها",
    version="1.0.0",
)

# الفواتير اللي مصدرها صورة مباشرة (سكان/صورة موبايل) - بتروح لموديل الـ
# vision على طول بدل ما نعدي على Tesseract الضعيف مع الصور خصوصًا العربي.
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------
VALID_EXPORT_FORMATS = {"markdown", "pdf", "html"}


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    max_results: int = Field(default=5, ge=1, le=10)
    # markdown (افتراضي) | pdf | html - ممكن تبعت واحدة كـ string، أو أكتر
    # من صيغة مرة واحدة كـ list (["markdown", "pdf"]) عشان يطلعوا كلهم
    # من نفس التشغيلة من غير ما نعيد البحث/التلخيص لكل صيغة
    export_format: str | list[str] = "markdown"
    # "ar" أو "en" - لو اتبعتت صراحة بتلغي الكشف التلقائي من نص السؤال.
    # مطلوبة لو السؤال مخلوط عربي/إنجليزي بنسبة معتبرة (هيرجع 422 وإلا).
    response_language: str | None = None

    def normalized_formats(self) -> list[str]:
        raw = self.export_format
        formats = [raw] if isinstance(raw, str) else raw
        # إزالة تكرار مع الحفاظ على الترتيب
        seen: dict[str, None] = {}
        for f in formats:
            seen[f.lower().strip()] = None
        return list(seen)


class ResearchResponse(BaseModel):
    query: str
    report_paths: list[str]
    export_formats: list[str]
    articles_count: int


class InvoiceResponse(BaseModel):
    invoice_id: str
    filename: str
    is_valid: bool
    errors: list[str]
    duplicate: bool = False
    sheets_synced: bool = True
    customer_email: str | None = None


# ----------------------------------------------------------------------
# Health check
# ----------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _render_pdf_pages_to_temp_images(pdf_path: Path) -> list[Path]:
    """
    لـ PDF سكان (مفيهوش نص مباشر كافي) - بنحوّل صفحاته لصور مؤقتة عشان
    نبعتها لموديل الـ vision بدل ما نعتمد على نص Tesseract الضعيف.
    """
    image_paths: list[Path] = []
    try:
        with fitz.open(pdf_path) as doc:
            if doc.page_count > 20:
                raise HTTPException(status_code=413, detail="Maximum 20 PDF pages")
            for page in doc:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as image:
                    img_path = Path(image.name)
                image_paths.append(img_path)
                page.get_pixmap(dpi=150).save(img_path)
        return image_paths
    except Exception:
        for image_path in image_paths:
            image_path.unlink(missing_ok=True)
        raise


# ----------------------------------------------------------------------
# Invoice pipeline — نفس خطوات run_invoice_pipeline.py بالظبط
# ----------------------------------------------------------------------
@app.post("/invoices/process", response_model=InvoiceResponse)
async def process_invoice(
    file: UploadFile = File(...),
    drive_file_id: str | None = Form(None),
) -> InvoiceResponse:
    # نحفظ الملف المرفوع مؤقتًا على الديسك عشان process_invoice_file بتاخد path
    suffix = Path(file.filename or "invoice.pdf").suffix.lower()
    if suffix not in IMAGE_EXTENSIONS | {".pdf"}:
        raise HTTPException(status_code=415, detail="Supported files: PDF, JPG, JPEG, PNG")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        size = 0
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > 20 * 1024 * 1024:
                Path(tmp.name).unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Maximum upload size is 20 MiB")
            tmp.write(chunk)
        tmp_path = Path(tmp.name)

    rendered_image_paths: list[Path] = []

    try:
        is_image_file = tmp_path.suffix.lower() in IMAGE_EXTENSIONS

        # 1) فحص التكرار - رجع دلوقتي عبر Supabase بدل Postgres (نفس منطق
        #    is_duplicate القديمة: SHA256 على الملف نفسه، مش على نص OCR).
        file_hash = compute_file_hash(tmp_path)
        if is_duplicate(file_hash):
            log.warning(f"الملف اتعالج قبل كده (hash={file_hash[:12]}...) - تخطي")
            return InvoiceResponse(
                invoice_id="",
                filename=file.filename,
                is_valid=False,
                errors=["الملف ده اتعالج قبل كده (مكرر)"],
                duplicate=True,
                sheets_synced=False,
            )

        invoice_id = str(uuid.uuid4())

        # 2) استخراج البيانات - في مسارين حسب مصدر الملف:
        if is_image_file:
            # صورة خام (سكان/موبايل) → موديل vision على طول، من غير Tesseract
            invoice_data = extract_invoice_data_from_images(str(tmp_path))
        else:
            extracted = process_invoice_file(tmp_path)
            if extracted.engine == "tesseract":
                # PDF سكان - نص Tesseract مش موثوق بما يكفي، نروح لموديل vision
                # بالصور نفسها (صفحات الـ PDF متحوّلة لصور) بدل النص الضعيف
                rendered_image_paths = _render_pdf_pages_to_temp_images(tmp_path)
                invoice_data = extract_invoice_data_from_images(
                    [str(p) for p in rendered_image_paths]
                )
            else:
                # PDF نصي أصلًا (pymupdf) - المسار النصي القديم كفاية وأدق
                invoice_data = extract_invoice_data(extracted.text)

        # 3) Validation
        validation = validate_invoice(invoice_data)

        # 4) Storage - Google Sheets (المصدر الوحيد للبيانات التفصيلية)
        sheets_synced = True
        try:
            append_invoice_row(
                invoice_id=invoice_id,
                drive_file_id=drive_file_id,
                source_filename=file.filename,
                invoice=invoice_data,
                validation=validation,
            )
        except SheetsWriteError as exc:
            sheets_synced = False
            log.warning(
                f"فشلت الكتابة على Google Sheets للفاتورة {invoice_id} "
                f"(hash={file_hash[:12]}...): {exc}"
            )

        # 5) Storage - Supabase (المصدر الكامل الآن: كل حقول الفاتورة +
        #    line_items، وهو نفسه اللي بيغني عن جدول تكرار منفصل)
        try:
            save_invoice_record(
                invoice_id=invoice_id,
                file_hash=file_hash,
                drive_file_id=drive_file_id,
                source_filename=file.filename,
                invoice=invoice_data,
                validation=validation,
                sheets_synced=sheets_synced,
            )
        except SupabaseWriteError as exc:
            log.warning(
                f"فشل حفظ الفاتورة {invoice_id} في Supabase - فحص التكرار "
                f"مش هيلاقيها في المرة الجاية لو اترفعت تاني، وتفاصيل line_items "
                f"مش هتتخزن في أي مكان لحد ما يتحل الفشل ده: {exc}"
            )

        log.info(
            f"انتهى معالجة الفاتورة {file.filename} | صالحة={validation.is_valid} "
            f"| id={invoice_id} | sheets_synced={sheets_synced}"
        )
        return InvoiceResponse(
            invoice_id=invoice_id,
            filename=file.filename,
            is_valid=validation.is_valid,
            errors=validation.errors,
            sheets_synced=sheets_synced,
            customer_email=invoice_data.customer_email,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.error(f"فشل معالجة الفاتورة {file.filename}: {exc}")
        raise HTTPException(status_code=500, detail="Pipeline failed; consult private server logs.") from exc
    finally:
        tmp_path.unlink(missing_ok=True)
        for p in rendered_image_paths:
            p.unlink(missing_ok=True)


# ----------------------------------------------------------------------
# Research pipeline — نفس خطوات run_research_pipeline.py بالظبط
# ----------------------------------------------------------------------
@app.post("/research/run", response_model=ResearchResponse)
def run_research(req: ResearchRequest) -> ResearchResponse:
    export_formats = req.normalized_formats()
    invalid = [f for f in export_formats if f not in VALID_EXPORT_FORMATS]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"export_format غير مدعوم: {invalid}. القيم المتاحة: {sorted(VALID_EXPORT_FORMATS)}",
        )
    if not export_formats:
        export_formats = ["markdown"]

    # لغة الرد: لو اليوزر حددها صراحة نستخدمها زي ما هي، وإلا نكتشفها من
    # نص السؤال. لو السؤال مخلوط عربي/إنجليزي بنسبة معتبرة، منخمنش -
    # بنرجع 422 يطلب من اليوزر يحدد لغة الرد صراحة عبر response_language.
    if req.response_language:
        target_language = req.response_language.lower().strip()
        if target_language not in ("ar", "en"):
            raise HTTPException(
                status_code=422,
                detail="response_language لازم يكون 'ar' أو 'en'",
            )
    else:
        detected = detect_query_language(req.query)
        if detected == "mixed":
            raise HTTPException(
                status_code=422,
                detail=(
                    "السؤال فيه عربي وإنجليزي مع بعض، ومش واضح تحب الرد يطلع بأنهي "
                    "لغة. ابعت الطلب تاني مع تحديد response_language='ar' أو 'en'."
                ),
            )
        target_language = detected

    try:
        # 1) Search - بنطلب نتايج زيادة (buffer) عشان لو صفحة اتحظرت أو
        #    رجعت فاضية، يفضل عندنا بدائل كفاية للوصول لـ max_results فعلي
        search_buffer = req.max_results + 3
        results = search_topic(req.query, max_results=search_buffer)
        if not results:
            raise HTTPException(status_code=404, detail="مفيش نتايج بحث لموضوع البحث ده")

        # 2) Browse
        urls = [r.url for r in results]
        pages = fetch_multiple_pages(urls)

        # صفحات الحظر (403/WAF) بترجع HTML "ناجح" ظاهريًا لكن محتواها رسالة
        # خطأ مش محتوى حقيقي - بنستبعدها هنا قبل ما توصل للـ Summarizer
        usable_pages = [p for p in pages if p.is_usable][: req.max_results]
        if not usable_pages:
            raise HTTPException(
                status_code=502,
                detail="كل نتايج البحث كانت صفحات محظورة أو فاضية - جرب موضوع بحث تاني",
            )

        # 3) Summarize - مرة واحدة بس، بغض النظر عن عدد الصيغ المطلوبة
        summaries = summarize_multiple(usable_pages, target_language=target_language)

        # 3.5) بناء متن التقرير النهائي (مقدمة + نقاط مشتركة + خاتمة) مرة
        #      واحدة هنا، بدل ما كل export function تنادي الـ LLM بنفسها -
        #      لو طلب اليوزر 3 صيغ مع بعض، كنا هنعمل نفس نداء الـ LLM 3
        #      مرات من غير داعي. دلوقتي نداء واحد بس بغض النظر عن عدد الصيغ.
        report_body = generate_final_report(req.query, summaries, target_language=target_language)

        # 4) Export - نولّد كل صيغة مطلوبة من نفس الملخصات ونفس المتن
        #    (من غير إعادة بحث/تلخيص/توليد متن لكل صيغة)
        export_fns = {
            "pdf": save_pdf_report,
            "html": save_html_report,
            "markdown": save_markdown_report,
        }
        report_paths = [
            str(
                export_fns[fmt](
                    req.query, summaries, target_language=target_language, report_body=report_body
                )
            )
            for fmt in export_formats
        ]

        log.info(f"التقارير جاهزة ({export_formats}): {report_paths}")

        return ResearchResponse(
            query=req.query,
            report_paths=report_paths,
            export_formats=export_formats,
            articles_count=len(summaries),
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.error(f"فشل research pipeline لـ '{req.query}' (export_format={export_formats}): {exc}")
        raise HTTPException(status_code=500, detail="Pipeline failed; consult private server logs.") from exc


@app.get("/research/report")
def get_research_report(path: str) -> FileResponse:
    """
    n8n مش شايف ملفات السيرفر مباشرة (شغال في Docker container منفصل)،
    فده بيرجع محتوى ملف التقرير كـ binary عشان n8n يقدر يرفقه بإيميل أو
    يرفعه على Drive. `path` هو نفس القيمة اللي رجعت في report_path من
    /research/run (مسار نسبي جوه مجلد reports/ بالظبط، مفيش خروج منه مسموح).
    """
    # حماية من path traversal - لازم الملف يكون فعليًا جوه REPORTS_DIR
    requested = (REPORTS_DIR / Path(path).name).resolve()
    reports_root = REPORTS_DIR.resolve()
    if reports_root not in requested.parents and requested != reports_root:
        raise HTTPException(status_code=400, detail="مسار غير مسموح")
    if not requested.is_file():
        raise HTTPException(status_code=404, detail="الملف مش موجود")

    return FileResponse(path=requested, filename=requested.name)