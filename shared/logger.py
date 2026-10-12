"""
Logging & Monitoring
=====================
Wrapper بسيط حول loguru عشان كل الموديولات تستخدم نفس شكل الـ logs
وتتسجل في نفس المكان (console + ملف يومي).
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger as _logger

from shared.config import settings

_LOG_DIR = Path(settings.log_dir)
_LOG_DIR.mkdir(parents=True, exist_ok=True)

_logger.remove()  # نشيل الإعداد الافتراضي

# Console
_logger.add(
    sys.stderr,
    level=settings.log_level,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{extra[pipeline]}</cyan> | "
        "<level>{message}</level>"
    ),
    colorize=True,
    filter=lambda record: record["extra"].setdefault("pipeline", "app") or True,
)

# ملف log يومي، بيحتفظ بآخر 14 يوم
_logger.add(
    _LOG_DIR / "ai_agents_hub_{time:YYYY-MM-DD}.log",
    level=settings.log_level,
    rotation="00:00",
    retention="14 days",
    encoding="utf-8",
)


def get_logger(pipeline: str):
    """
    استخدام:
        from shared.logger import get_logger
        log = get_logger("invoice_extraction")
        log.info("بدأ استخراج الفاتورة X")
    """
    return _logger.bind(pipeline=pipeline)
