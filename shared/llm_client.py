"""
shared/llm_client.py
---------------------
Unified LLM Client — Gemini (أساسي) + Groq (fallback)

المزود الأساسي: Gemini API (GEMINI_API_KEY في .env، لازم).
لو Gemini فشل (rate limit، انقطاع اتصال، خطأ 5xx بعد كل المحاولات) بيقع
تلقائيًا على Groq (GROQ_API_KEY، اختياري - لو مش موجود بيرجع خطأ Gemini
الأصلي بدل ما يحاول fallback لموديل مش موجود).

كل الدوال (generate_text / generate_structured / generate_structured_from_images)
بترجع نفس الشكل بالظبط بغض النظر عن مين اللي فعليًا رد (Gemini ولا Groq)،
عشان الكود اللي بينادي عليها (extractor_agent.py, summarizer_agent.py) يفضل
provider-agnostic زي ما هو.
"""

import os
import json
import time
import base64
import logging
import mimetypes
from typing import Optional, Type, TypeVar

from shared.config import settings  # Load project configuration before reading environment.

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPICallError, ResourceExhausted

from groq import Groq
from groq import APIError, APIConnectionError, RateLimitError
from pydantic import BaseModel, ValidationError

logger = logging.getLogger("shared.llm_client")

T = TypeVar("T", bound=BaseModel)

# ------------------------------------------------------------------
# الإعدادات — Gemini (أساسي)
# ------------------------------------------------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", settings.gemini_model)
GEMINI_EXTRACTION_MODEL = os.getenv("GEMINI_EXTRACTION_MODEL", GEMINI_MODEL)
GEMINI_SUMMARIZATION_MODEL = os.getenv("GEMINI_SUMMARIZATION_MODEL", GEMINI_MODEL)
# Gemini multimodal بطبعه - نفس الموديل بيقرا صور من غير ما نحتاج موديل منفصل
GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", GEMINI_MODEL)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ------------------------------------------------------------------
# الإعدادات — Groq (fallback بس، مش أساسي)
# ------------------------------------------------------------------

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_EXTRACTION_MODEL = os.getenv("GROQ_EXTRACTION_MODEL", GROQ_MODEL)
GROQ_SUMMARIZATION_MODEL = os.getenv("GROQ_SUMMARIZATION_MODEL", GROQ_MODEL)
# openai/gpt-oss-120b نص فقط، فلازم موديل vision منفصل لو Gemini نفسه فشل
# وقعنا على Groq كـ fallback لحالة فيها صور
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
MAX_IMAGES_PER_REQUEST = 3  # حد qwen3.8-27b على Groq (Gemini مفهوش الحد ده)

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
REQUEST_TIMEOUT_SECONDS = 60

groq_client: Optional[Groq] = None
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY, timeout=REQUEST_TIMEOUT_SECONDS)
else:
    logger.warning(
        "GROQ_API_KEY مش موجود في .env — الـ fallback عند فشل Gemini مش هيشتغل. "
        "الموصى بيه: ضيف GROQ_API_KEY عشان الاستمرارية لو Gemini وقع أو ضرب rate limit."
    )


def _fallback_available() -> bool:
    return groq_client is not None


# ------------------------------------------------------------------
# دالة عامة لعمل completion نصي (تستخدمها LLM Summarizer Agent)
# ------------------------------------------------------------------

def _gemini_generate_text(prompt, system_prompt, model, temperature, max_tokens):
    if not GEMINI_API_KEY:
        raise RuntimeError("Configure GEMINI_API_KEY to use Gemini.")
    gen_model = genai.GenerativeModel(model_name=model, system_instruction=system_prompt)
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = gen_model.generate_content(
                prompt,
                request_options={"timeout": REQUEST_TIMEOUT_SECONDS},
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )
            _warn_if_truncated_gemini(response, max_tokens)
            return response.text.strip()
        except ResourceExhausted as e:
            last_error = e
            wait = RETRY_BACKOFF_SECONDS * attempt * 2
            logger.warning(f"Gemini rate limit (محاولة {attempt}), بستنى {wait}s: {e}")
            time.sleep(wait)
        except GoogleAPICallError as e:
            last_error = e
            logger.error(f"خطأ في الاتصال بـ Gemini (محاولة {attempt}): {e}")
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"فشل استدعاء Gemini بعد {MAX_RETRIES} محاولات: {last_error}")


def _warn_if_truncated_gemini(response, max_tokens):
    """لو الرد اتقطع لأنه ضرب سقف max_output_tokens، نسجل تحذير واضح في
    اللوج بدل ما نرجع نص ناقص بصمت من غير أي إشارة للمشكلة. مهم خصوصًا
    للعربي لأن نفس عدد الكلمات بياخد رموز (tokens) أكتر من الإنجليزي."""
    try:
        finish_reason = response.candidates[0].finish_reason
        if str(finish_reason) in ("2", "MAX_TOKENS", "FinishReason.MAX_TOKENS"):
            logger.warning(
                f"⚠️ رد Gemini اتقطع لأنه ضرب سقف max_output_tokens={max_tokens} - "
                "النص الراجع ممكن يكون ناقص/متوقف في نص جملة. لو ده بيتكرر، "
                "زوّد max_tokens في نداء generate_text."
            )
    except (IndexError, AttributeError):
        pass  # مفيش candidates أو finish_reason - تجاهل، مش حرج


def _groq_generate_text(prompt, system_prompt, model, temperature, max_tokens):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = groq_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if response.choices[0].finish_reason == "length":
                logger.warning(
                    f"⚠️ رد Groq اتقطع لأنه ضرب سقف max_tokens={max_tokens} - "
                    "النص الراجع ممكن يكون ناقص/متوقف في نص جملة."
                )
            return response.choices[0].message.content.strip()
        except RateLimitError as e:
            last_error = e
            wait = RETRY_BACKOFF_SECONDS * attempt * 2
            logger.warning(f"Groq rate limit (محاولة {attempt}), بستنى {wait}s: {e}")
            time.sleep(wait)
        except (APIConnectionError, APIError) as e:
            last_error = e
            logger.error(f"خطأ في الاتصال بـ Groq (محاولة {attempt}): {e}")
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"فشل استدعاء Groq (fallback) بعد {MAX_RETRIES} محاولات: {last_error}")


def generate_text(
    prompt: str,
    system_prompt: Optional[str] = None,
    model: str = GEMINI_SUMMARIZATION_MODEL,
    temperature: float = 0.3,
    max_tokens: int = 3000,
    fallback_model: str = GROQ_SUMMARIZATION_MODEL,
) -> str:
    """
    استدعاء نصي حر. Gemini أولًا، ولو فشل نهائيًا (وGROQ_API_KEY موجود)
    بيقع تلقائيًا على Groq بدل ما يفشل الطلب كله.
    """
    try:
        return _gemini_generate_text(prompt, system_prompt, model, temperature, max_tokens)
    except RuntimeError as gemini_error:
        if not _fallback_available():
            raise
        logger.warning(f"Gemini فشل نهائيًا، بنجرب Groq كـ fallback: {gemini_error}")
        return _groq_generate_text(prompt, system_prompt, fallback_model, temperature, max_tokens)


# ------------------------------------------------------------------
# دالة استخراج JSON منظم (تستخدمها LLM Extraction Agent)
# ------------------------------------------------------------------

def _schema_hint(schema: Type[T]) -> str:
    return (
        f"\n\nأعد الإجابة بصيغة JSON فقط، بدون أي نص إضافي أو Markdown أو شرح، "
        f"مطابقة تمامًا لهذا الـ schema:\n{schema.model_json_schema()}"
    )


def _gemini_generate_structured(prompt, schema, system_prompt, model, temperature):
    if not GEMINI_API_KEY:
        raise RuntimeError("Configure GEMINI_API_KEY to use Gemini.")
    gen_model = genai.GenerativeModel(model_name=model, system_instruction=system_prompt)
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = gen_model.generate_content(
                prompt,
                request_options={"timeout": REQUEST_TIMEOUT_SECONDS},
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    response_mime_type="application/json",
                ),
            )
            try:
                data = json.loads(response.text)
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as parse_err:
                logger.warning(
                    f"فشل الـ parsing/validation لمخرجات Gemini (محاولة {attempt}): {parse_err}"
                )
                last_error = parse_err
                continue
        except ResourceExhausted as e:
            last_error = e
            wait = RETRY_BACKOFF_SECONDS * attempt * 2
            logger.warning(f"Gemini rate limit (محاولة {attempt}), بستنى {wait}s: {e}")
            time.sleep(wait)
        except GoogleAPICallError as e:
            last_error = e
            logger.error(f"خطأ في الاتصال بـ Gemini (محاولة {attempt}): {e}")
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"فشل استخراج بيانات منظمة عبر Gemini بعد {MAX_RETRIES} محاولات: {last_error}")


def _groq_generate_structured(prompt, schema, system_prompt, model, temperature):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt + _schema_hint(schema)})

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = groq_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            try:
                data = json.loads(response.choices[0].message.content)
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as parse_err:
                logger.warning(
                    f"فشل الـ parsing/validation لمخرجات Groq (محاولة {attempt}): {parse_err}"
                )
                last_error = parse_err
                continue
        except RateLimitError as e:
            last_error = e
            wait = RETRY_BACKOFF_SECONDS * attempt * 2
            logger.warning(f"Groq rate limit (محاولة {attempt}), بستنى {wait}s: {e}")
            time.sleep(wait)
        except (APIConnectionError, APIError) as e:
            last_error = e
            logger.error(f"خطأ في الاتصال بـ Groq (محاولة {attempt}): {e}")
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(
        f"فشل استخراج بيانات منظمة عبر Groq (fallback) بعد {MAX_RETRIES} محاولات: {last_error}"
    )


def generate_structured(
    prompt: str,
    schema: Type[T],
    system_prompt: Optional[str] = None,
    model: str = GEMINI_EXTRACTION_MODEL,
    temperature: float = 0.0,
    fallback_model: str = GROQ_EXTRACTION_MODEL,
) -> T:
    """
    استخراج JSON منظم متحقق منه بـ Pydantic. Gemini أولًا (response_mime_type
    = application/json)، ولو فشل نهائيًا بيقع على Groq (response_format=json_object).
    """
    full_prompt = prompt + _schema_hint(schema)
    try:
        return _gemini_generate_structured(full_prompt, schema, system_prompt, model, temperature)
    except RuntimeError as gemini_error:
        if not _fallback_available():
            raise
        logger.warning(f"Gemini فشل نهائيًا في الاستخراج المنظم، بنجرب Groq: {gemini_error}")
        return _groq_generate_structured(prompt, schema, system_prompt, fallback_model, temperature)


# ------------------------------------------------------------------
# دوال مساعدة لتجهيز الصور
# ------------------------------------------------------------------

def _read_image_bytes_and_mime(image_path: str) -> tuple[bytes, str]:
    mime_type, _ = mimetypes.guess_type(image_path)
    if not mime_type:
        mime_type = "image/jpeg"
    with open(image_path, "rb") as f:
        return f.read(), mime_type


def _encode_image_to_data_url(image_path: str) -> str:
    """يحوّل ملف صورة محلي إلى data URL base64 — مستخدمة في مسار Groq fallback فقط."""
    raw, mime_type = _read_image_bytes_and_mime(image_path)
    encoded = base64.b64encode(raw).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


# ------------------------------------------------------------------
# دالة استخراج JSON منظم من صورة (Vision) — تستخدمها Extraction Agent
# لما مصدر الفاتورة صورة (مش نص جاهز من OCR نصي)
# ------------------------------------------------------------------

def _gemini_generate_structured_from_images(image_paths, schema, prompt, system_prompt, model, temperature):
    if not GEMINI_API_KEY:
        raise RuntimeError("Configure GEMINI_API_KEY to use Gemini.")
    gen_model = genai.GenerativeModel(model_name=model, system_instruction=system_prompt)
    parts = [prompt]
    for path in image_paths:
        raw, mime_type = _read_image_bytes_and_mime(path)
        parts.append({"mime_type": mime_type, "data": raw})

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = gen_model.generate_content(
                parts,
                request_options={"timeout": REQUEST_TIMEOUT_SECONDS},
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    response_mime_type="application/json",
                ),
            )
            try:
                data = json.loads(response.text)
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as parse_err:
                logger.warning(
                    f"فشل الـ parsing/validation لمخرجات Gemini vision (محاولة {attempt}): {parse_err}"
                )
                last_error = parse_err
                continue
        except ResourceExhausted as e:
            last_error = e
            wait = RETRY_BACKOFF_SECONDS * attempt * 2
            logger.warning(f"Gemini rate limit (محاولة {attempt}), بستنى {wait}s: {e}")
            time.sleep(wait)
        except GoogleAPICallError as e:
            last_error = e
            logger.error(f"خطأ في الاتصال بـ Gemini (محاولة {attempt}): {e}")
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(
        f"فشل استخراج بيانات منظمة من الصورة عبر Gemini بعد {MAX_RETRIES} محاولات: {last_error}"
    )


def _groq_generate_structured_from_images(image_paths, schema, prompt, system_prompt, model, temperature):
    if len(image_paths) > MAX_IMAGES_PER_REQUEST:
        raise ValueError(
            f"موديل الـ vision fallback ({model}) بيقبل {MAX_IMAGES_PER_REQUEST} صور كحد أقصى "
            f"في الطلب الواحد، وانت بعتّ {len(image_paths)}."
        )

    content = [{"type": "text", "text": prompt + _schema_hint(schema)}]
    for path in image_paths:
        content.append({"type": "image_url", "image_url": {"url": _encode_image_to_data_url(path)}})

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": content})

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = groq_client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            try:
                data = json.loads(response.choices[0].message.content)
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as parse_err:
                logger.warning(
                    f"فشل الـ parsing/validation لمخرجات موديل الـ vision (محاولة {attempt}): {parse_err}"
                )
                last_error = parse_err
                continue
        except RateLimitError as e:
            last_error = e
            wait = RETRY_BACKOFF_SECONDS * attempt * 2
            logger.warning(f"Groq rate limit (محاولة {attempt}), بستنى {wait}s: {e}")
            time.sleep(wait)
        except (APIConnectionError, APIError) as e:
            last_error = e
            logger.error(f"خطأ في الاتصال بـ Groq (محاولة {attempt}): {e}")
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise RuntimeError(
        f"فشل استخراج بيانات منظمة من الصورة عبر Groq (fallback) بعد {MAX_RETRIES} محاولات: {last_error}"
    )


def generate_structured_from_images(
    image_paths: list[str],
    schema: Type[T],
    prompt: str,
    system_prompt: Optional[str] = None,
    model: str = GEMINI_VISION_MODEL,
    temperature: float = 0.0,
    fallback_model: str = GROQ_VISION_MODEL,
) -> T:
    """
    استخراج JSON منظم من صورة/صور فاتورة. Gemini أولًا (multimodal بطبعه،
    مفيهوش حد صارم لعدد الصور)، ولو فشل نهائيًا بيقع على Groq vision model
    (qwen، محدود بـ MAX_IMAGES_PER_REQUEST صور).
    """
    if not image_paths:
        raise ValueError("لازم تبعت مسار صورة واحدة على الأقل.")

    try:
        return _gemini_generate_structured_from_images(
            image_paths, schema, prompt, system_prompt, model, temperature
        )
    except RuntimeError as gemini_error:
        if not _fallback_available():
            raise
        logger.warning(f"Gemini فشل نهائيًا في استخراج الصورة، بنجرب Groq vision: {gemini_error}")
        return _groq_generate_structured_from_images(
            image_paths, schema, prompt, system_prompt, fallback_model, temperature
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    summary = generate_text(
        prompt="لخص لي في سطرين: الذكاء الاصطناعي التوليدي بيغير طريقة عمل الشركات.",
        system_prompt="أنت مساعد يلخص المحتوى بالعربية بإيجاز ووضوح.",
    )
    print("Summary:", summary)

    class InvoiceData(BaseModel):
        vendor_name: str
        total_amount: float
        currency: str
        invoice_date: str

    invoice = generate_structured(
        prompt="استخرج بيانات الفاتورة من النص التالي: مورد: شركة النور، الإجمالي: 1500 جنيه، التاريخ: 2026-08-15",
        schema=InvoiceData,
        system_prompt="أنت وكيل استخراج بيانات فواتير دقيق.",
    )
    print("Invoice:", invoice)