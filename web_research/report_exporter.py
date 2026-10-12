"""
Report Exporter
=================
بيدمج ملخصات المقالات (من summarizer_agent) في تقرير، وبيقدر يصدّره بـ 3
صيغ: Markdown (الافتراضي/الأساسي)، HTML مستقل، أو PDF (زي ما مطلوب في
مستند التخطيط الأصلي: "Markdown, PDF, or HTML report").
"""

from __future__ import annotations

from html import escape
from urllib.parse import urlsplit
from uuid import uuid4
from datetime import datetime
from pathlib import Path

from shared.logger import get_logger

from web_research.summarizer_agent import ArticleSummary, generate_final_report

log = get_logger("web_research.report_exporter")

REPORTS_DIR = Path("./reports")


def _safe_filename_stem(query: str) -> str:
    safe_name = "".join(c if c.isalnum() or c in (" ", "-") else "_" for c in query)[:60].strip()
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}_{safe_name}"


# ------------------------------------------------------------------
# Markdown
# ------------------------------------------------------------------

def build_markdown_report(
    query: str,
    summaries: list[ArticleSummary],
    target_language: str = "ar",
    report_body: str | None = None,
) -> str:
    """
    بيبني ريبورت واحد متصل (مقدمة → نقاط مشتركة بين المصادر → خاتمة).

    report_body: لو الـ caller عنده متن جاهز اتولّد قبل كده (عشان مش
    عايز يعيد نداء LLM لكل صيغة تصدير)، يبعته هنا ويتحط زي ما هو.
    لو مبعتوش، بيتولد هنا بنداء generate_final_report() عادي (بيفيد
    لو حد بينادي الدالة دي لوحدها من غير المرور بـ api.py).
    قائمة المصادر بترجع في الآخر دايمًا (مش من الـ LLM) عشان تفضل دقيقة
    100% حتى لو الموديل نسي يذكر مصدر في المتن.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = report_body if report_body is not None else generate_final_report(
        query, summaries, target_language=target_language
    )

    sources_heading = "## المصادر" if target_language == "ar" else "## Sources"
    sources_lines = [f"{i}. [{s.title or s.url}]({s.url})" for i, s in enumerate(summaries, start=1)]

    title_label = "تقرير بحث" if target_language == "ar" else "Research Report"
    created_label = "تم الإنشاء في" if target_language == "ar" else "Generated on"
    header = f"# {title_label}: {query}\n*{created_label}: {timestamp}*\n\n---\n"
    footer = f"\n\n---\n\n{sources_heading}\n\n" + "\n".join(sources_lines)

    return header + "\n" + body + footer


def save_markdown_report(
    query: str,
    summaries: list[ArticleSummary],
    stem: str | None = None,
    target_language: str = "ar",
    report_body: str | None = None,
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    content = build_markdown_report(
        query, summaries, target_language=target_language, report_body=report_body
    )

    filename = f"{stem or _safe_filename_stem(query)}.md"
    file_path = REPORTS_DIR / filename

    file_path.write_text(content, encoding="utf-8")
    log.info(f"تم حفظ التقرير (Markdown) في: {file_path}")
    return file_path


# ------------------------------------------------------------------
# HTML مستقل (Standalone) — مش تحويل من Markdown، ليه تنسيق خاص بيه
# عشان يتفتح مباشرة في المتصفح أو يترفق في إيميل
# ------------------------------------------------------------------

def _render_html(
    query: str,
    summaries: list[ArticleSummary],
    target_language: str = "ar",
    report_body: str | None = None,
) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    is_rtl = target_language == "ar"
    dir_attr = "rtl" if is_rtl else "ltr"
    sources_heading = "المصادر" if is_rtl else "Sources"

    body_html = report_body if report_body is not None else generate_final_report(
        query, summaries, target_language=target_language
    )
    # الريبورت جاي Markdown من الـ LLM؛ تحويل بسيط للفقرات (مفيش داعي
    # لمكتبة markdown2 هنا، نفس المنطق المستخدم في الـ PDF path)
    body_paragraphs = "".join(f"<p>{escape(line)}</p>" for line in body_html.split("\n") if line.strip())

    query = escape(query)
    sources_html = "".join(
        f'<li><a href="{escape(s.url, quote=True) if urlsplit(s.url).scheme in ("http", "https") else "#"}" target="_blank" rel="noopener noreferrer">{escape(s.title or s.url)}</a></li>' for s in summaries
    )

    return f"""<!DOCTYPE html>
<html dir="{dir_attr}" lang="{target_language}">
<head>
    <meta charset="utf-8">
    <title>تقرير بحث: {query}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Arial, sans-serif; line-height: 1.7;
                max-width: 800px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; }}
        h1 {{ border-bottom: 3px solid #2563eb; padding-bottom: 10px; }}
        .timestamp {{ color: #666; font-size: 0.9em; margin-bottom: 30px; }}
        .sources {{ margin-top: 32px; padding-top: 24px; border-top: 1px solid #e5e5e5; }}
        .sources a {{ color: #2563eb; word-break: break-all; font-size: 0.9em; }}
    </style>
</head>
<body>
    <h1>تقرير بحث: {query}</h1>
    <p class="timestamp">تم الإنشاء في: {timestamp}</p>
    {body_paragraphs}
    <section class="sources">
        <h2>{sources_heading}</h2>
        <ol>{sources_html}</ol>
    </section>
</body>
</html>"""


def save_html_report(
    query: str,
    summaries: list[ArticleSummary],
    stem: str | None = None,
    target_language: str = "ar",
    report_body: str | None = None,
) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    content = _render_html(
        query, summaries, target_language=target_language, report_body=report_body
    )

    filename = f"{stem or _safe_filename_stem(query)}.html"
    file_path = REPORTS_DIR / filename

    file_path.write_text(content, encoding="utf-8")
    log.info(f"تم حفظ التقرير (HTML) في: {file_path}")
    return file_path


# ------------------------------------------------------------------
# PDF — عبر تحويل نفس الـ Markdown (بـ markdown2) ثم weasyprint
# ------------------------------------------------------------------

def convert_markdown_to_pdf(markdown_path: Path, target_language: str = "ar") -> Path:
    """
    تحويل تقرير Markdown موجود بالفعل على الديسك لـ PDF باستخدام weasyprint.
    بيحتاج تحويل Markdown -> HTML أولًا (markdown2) قبل التحويل النهائي لـ PDF.

    target_language: بيحدد اتجاه الصفحة (rtl لعربي، ltr لإنجليزي/غيره).
    قبل كده كان الاتجاه rtl ثابت دايمًا بغض النظر عن لغة التقرير الفعلية،
    وده كان بيقلب أعمدة أي جدول أو محتوى إنجليزي بصريًا.
    """
    import markdown2
    from weasyprint import HTML

    html_content = markdown2.markdown(
        markdown_path.read_text(encoding="utf-8"), extras=["tables"], safe_mode="escape"
    )

    is_rtl = target_language == "ar"
    dir_attr = "rtl" if is_rtl else "ltr"
    align = "right" if is_rtl else "left"
    # مشكلة معروفة (لسه موجودة في حالة عربي بس): الاعتماد على dir="rtl"
    # في الـ <html> بس مش كفاية - لازم direction صريحة في الـ CSS كمان +
    # خط فعليًا بيدعم تشكيل الحروف العربية (Arabic shaping/joining)، لأن
    # 'Arial' مش موجود على Linux أصلاً وبيقع على خط بديل بيطلع الحروف
    # منفصلة ومعكوسة. الخطوط دي لازم تكون متثبتة على السيرفر (مثلاً على
    # Ubuntu/Debian): sudo apt-get install fonts-noto-naskh-arabic fonts-noto-core
    full_html = f"""
    <html dir="{dir_attr}" lang="{target_language}">
    <head><meta charset="utf-8"><style>
        body {{
            font-family: 'Noto Naskh Arabic', 'Noto Sans Arabic', 'Amiri',
                         'Arial', 'DejaVu Sans', sans-serif;
            direction: {dir_attr};
            line-height: 1.8;
        }}
        h1, h2, h3 {{ direction: {dir_attr}; text-align: {align}; }}
        p {{ direction: {dir_attr}; text-align: {align}; }}
        /* list-style-position: inside عشان الـ marker (النقطة) يفضل
           ملتصق بالنص جوه نفس السطر - من غيرها weasyprint بيفصل
           الـ markers عن نصها في القوائم RTL ويجمعهم في آخر الصفحة */
        ul, ol {{ direction: {dir_attr}; text-align: {align};
                  list-style-position: inside;
                  padding-{'right' if is_rtl else 'left'}: 0; }}
        li {{ direction: {dir_attr}; text-align: {align}; }}
        a {{ direction: ltr; unicode-bidi: embed; }}
        /* الجداول لازم اتجاهها يتبع لغة التقرير مش يتقلب معكوس */
        table {{ direction: {dir_attr}; width: 100%; border-collapse: collapse; }}
        th, td {{ direction: {dir_attr}; text-align: {align};
                  border: 1px solid #ccc; padding: 6px 10px; }}
    </style></head>
    <body>{html_content}</body>
    </html>
    """

    pdf_path = markdown_path.with_suffix(".pdf")
    def deny_resources(url, *args, **kwargs):
        raise ValueError("External PDF resources are disabled")

    HTML(string=full_html, url_fetcher=deny_resources).write_pdf(str(pdf_path))
    log.info(f"تم تحويل التقرير لـ PDF: {pdf_path}")
    return pdf_path


def save_pdf_report(
    query: str,
    summaries: list[ArticleSummary],
    stem: str | None = None,
    target_language: str = "ar",
    report_body: str | None = None,
) -> Path:
    """
    اختصار مباشر: يبني تقرير Markdown مؤقت (نفس stem) ثم يحوّله PDF على طول.
    مفيد لما الـ caller عايز PDF بس من غير ما يدير خطوة الـ Markdown بنفسه.
    """
    md_path = save_markdown_report(
        query, summaries, stem=stem, target_language=target_language, report_body=report_body
    )
    return convert_markdown_to_pdf(md_path, target_language=target_language)