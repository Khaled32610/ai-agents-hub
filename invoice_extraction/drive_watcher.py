"""
Drive Watcher (اختياري)
=========================
لو قررتوا تستغنوا عن n8n Google Drive Trigger وتعملوا الـ polling بنفسكوا
من كود بايثون مباشرة. مش أولوية دلوقتي لأن n8n بيغطي الوظيفة دي جاهز،
لكن سيبناها كخيار احتياطي أو لو حبيتوا تشغلوها كـ cron job منفصل.

ملاحظة: محتاج google-api-python-client (مش مضاف في requirements.txt
حاليًا) لو هتفعلوا الملف ده فعليًا.
"""

from __future__ import annotations

from shared.config import settings
from shared.logger import get_logger

log = get_logger("invoice_extraction.drive_watcher")


def list_new_files_since(last_checked_timestamp: str) -> list[dict]:
    """
    TODO: تفعيل الاتصال بـ Google Drive API باستخدام
    settings.google_drive_credentials_json و settings.google_sheet_id
    (أو مجلد Drive محدد) لجلب الملفات الجديدة بعد last_checked_timestamp.

    حاليًا الوظيفة دي مغطاة عبر n8n Google Drive Trigger (n8n/workflows/invoice_extraction.json)
    فمفيش داعي نفعلها إلا لو قررنا نستغني عن n8n لجزء المراقبة.
    """
    log.warning("drive_watcher.list_new_files_since لسه TODO - غير مفعّلة، استخدم n8n Trigger بدلها")
    raise NotImplementedError(
        "لسه متعملتش. المراقبة حاليًا شغالة عبر n8n Google Drive Node."
    )
