"""
Config & Secrets Manager
=========================
نقطة واحدة لتحميل كل متغيرات البيئة، بحيث أي موديول تاني في المشروع
(invoice_extraction أو web_research) يستورد `settings` بس ولا يلمس os.environ مباشرة.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# تحميل ملف .env من جذر المشروع
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _get(key: str, default: str | None = None) -> str | None:
    return os.getenv(key, default)


def _get_required(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(
            f"متغير البيئة '{key}' مطلوب وغير موجود في .env"
        )
    return value


@dataclass(frozen=True)
class Settings:
    # --- LLM (Gemini - أساسي) ---
    default_llm_provider: str = field(default_factory=lambda: _get("DEFAULT_LLM_PROVIDER", "gemini"))
    default_llm_model: str = field(default_factory=lambda: _get("DEFAULT_LLM_MODEL", "gemini-2.0-flash"))
    gemini_model: str = field(default_factory=lambda: _get("GEMINI_MODEL", "gemini-2.0-flash"))
    gemini_extraction_model: str = field(default_factory=lambda: _get("GEMINI_EXTRACTION_MODEL", "gemini-2.0-flash"))
    gemini_summarization_model: str = field(default_factory=lambda: _get("GEMINI_SUMMARIZATION_MODEL", "gemini-2.0-flash"))
    gemini_api_key: str | None = field(default_factory=lambda: _get("GEMINI_API_KEY"))

    # --- LLM (Groq - fallback تلقائي لو Gemini وقع) ---
    groq_model: str = field(default_factory=lambda: _get("GROQ_MODEL", "openai/gpt-oss-120b"))
    groq_extraction_model: str = field(default_factory=lambda: _get("GROQ_EXTRACTION_MODEL", "openai/gpt-oss-120b"))
    groq_summarization_model: str = field(default_factory=lambda: _get("GROQ_SUMMARIZATION_MODEL", "openai/gpt-oss-120b"))
    groq_api_key: str | None = field(default_factory=lambda: _get("GROQ_API_KEY"))

    # --- LLM (اختياري - مزودين تانيين لو احتجناهم لاحقًا) ---
    openai_api_key: str | None = field(default_factory=lambda: _get("OPENAI_API_KEY"))
    anthropic_api_key: str | None = field(default_factory=lambda: _get("ANTHROPIC_API_KEY"))

    # --- Search (SerpAPI - أساسي، Tavily - fallback تلقائي) ---
    serpapi_key: str | None = field(default_factory=lambda: _get("SERPAPI_KEY"))
    tavily_api_key: str | None = field(default_factory=lambda: _get("TAVILY_API_KEY"))

    # --- Google ---
    google_drive_credentials_json: str | None = field(
        default_factory=lambda: _get("GOOGLE_DRIVE_CREDENTIALS_JSON")
    )
    google_sheet_id: str | None = field(default_factory=lambda: _get("GOOGLE_SHEET_ID"))

    # --- Supabase (فحص التكرار + سجل الفواتير المُعالَجة) ---
    supabase_url: str | None = field(default_factory=lambda: _get("SUPABASE_URL"))
    supabase_key: str | None = field(default_factory=lambda: _get("SUPABASE_KEY"))

    # --- n8n ---
    n8n_webhook_url: str = field(default_factory=lambda: _get("N8N_WEBHOOK_URL", "http://localhost:5678/"))

    # --- OCR ---
    tesseract_lang: str = field(default_factory=lambda: _get("TESSERACT_LANG", "ara+eng"))

    # --- Logging ---
    log_level: str = field(default_factory=lambda: _get("LOG_LEVEL", "INFO"))
    log_dir: str = field(default_factory=lambda: _get("LOG_DIR", "./logs"))

    def require_llm_key(self, provider: str | None = None) -> str:
        """يرجع الـ API key المطلوب حسب الـ provider، ويرمي خطأ واضح لو ناقص."""
        provider = (provider or self.default_llm_provider).lower()
        mapping = {
            "gemini": self.gemini_api_key,
            "groq": self.groq_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
        }
        key = mapping.get(provider)
        if not key:
            raise EnvironmentError(
                f"مفيش API key متسجل لـ provider='{provider}'. "
                f"تأكد من {provider.upper()}_API_KEY في .env"
            )
        return key


settings = Settings()