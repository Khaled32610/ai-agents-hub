"""
Browser Agent
==============
بيستخدم Playwright (headless) عشان يزور روابط نتايج البحث ويسحب المحتوى
الكامل (خصوصًا الصفحات اللي المحتوى بتاعها متولد بـ JS ومش هيبان في
snippet الـ Tavily وحده).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright

from shared.logger import get_logger
from shared.url_safety import require_public_url

log = get_logger("web_research.browser_agent")

DEFAULT_TIMEOUT_MS = 20_000
MAX_CONTENT_CHARS = 15_000  # حماية من صفحات ضخمة تفجر الـ context بتاع الـ LLM
MIN_USEFUL_CHARS = 300  # صفحات أقصر من كده غالبًا صفحة حظر/خطأ مش محتوى حقيقي
MAX_CONCURRENT_PAGES = 5  # حد أقصى لعدد الـ tabs المفتوحة في نفس اللحظة (حماية من استهلاك رام/CPU زيادة)

# عبارات شائعة في صفحات الحظر (WAF/403/Cloudflare) بلغتين، عشان نستبعدها
# قبل ما توصل للـ Summarizer بدل ما "تتلخص" كأنها محتوى حقيقي
_BLOCK_MARKERS = [
    "access denied",
    "403 forbidden",
    "تم حظر الوصول",
    "تم رفض الوصول",
    "تم منع طلب الدخول",
    "www.alghad.tv",  # احتياطي: لو رجع نفس نص رسالة الحظر بعينها
]


@dataclass
class PageContent:
    url: str
    title: str
    text: str
    fetch_error: str | None = None

    @property
    def is_usable(self) -> bool:
        """صفحة سليمة فعليًا: مفيهاش fetch_error، وطولها كافي، ومفيهاش علامات حظر."""
        if self.fetch_error:
            return False
        if len(self.text) < MIN_USEFUL_CHARS:
            return False
        lowered = self.text.lower()
        return not any(marker.lower() in lowered for marker in _BLOCK_MARKERS)


def fetch_page_content(url: str) -> PageContent:
    """يفتح صفحة واحدة ويرجع النص الظاهر فيها (body innerText).

    ملاحظة: مش مستخدمة في الـ pipeline الفعلي (api.py بينادي على
    fetch_multiple_pages دايمًا حتى لرابط واحد) - سايبينها بس كأداة
    debugging سريعة لاختبار رابط واحد يدويًا من الـ REPL/شل."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            require_public_url(url)
            page = browser.new_page()
            def guard(route):
                try:
                    require_public_url(route.request.url)
                except (ValueError, OSError):
                    route.abort()
                else:
                    route.continue_()
            page.route("**/*", guard)
            page.goto(url, timeout=DEFAULT_TIMEOUT_MS, wait_until="domcontentloaded")
            title = page.title()
            text = page.inner_text("body")
            browser.close()

        text = text.strip()[:MAX_CONTENT_CHARS]
        log.info(f"تم سحب {len(text)} حرف من {url}")
        return PageContent(url=url, title=title, text=text)

    except Exception as exc:  # noqa: BLE001
        log.warning(f"فشل جلب محتوى {url}: {exc}")
        return PageContent(url=url, title="", text="", fetch_error=str(exc))


async def _fetch_one_page(browser, url: str, semaphore: asyncio.Semaphore) -> PageContent:
    """يفتح تبويب واحد لرابط واحد. الـ semaphore بيحدد أقصى عدد تبويبات شغالة مع بعض."""
    async with semaphore:
        page = None
        try:
            await asyncio.to_thread(require_public_url, url)
            page = await browser.new_page()
            async def guard(route):
                try:
                    await asyncio.to_thread(require_public_url, route.request.url)
                except (ValueError, OSError):
                    await route.abort()
                else:
                    await route.continue_()
            await page.route("**/*", guard)
            await page.goto(url, timeout=DEFAULT_TIMEOUT_MS, wait_until="domcontentloaded")
            title = await page.title()
            text = (await page.inner_text("body")).strip()[:MAX_CONTENT_CHARS]
            log.info(f"تم سحب {len(text)} حرف من {url}")
            return PageContent(url=url, title=title, text=text)
        except Exception as exc:  # noqa: BLE001
            log.warning(f"فشل جلب محتوى {url}: {exc}")
            return PageContent(url=url, title="", text="", fetch_error=str(exc))
        finally:
            if page is not None:
                await page.close()


async def _fetch_multiple_pages_async(urls: list[str]) -> list[PageContent]:
    """يفتح متصفح واحد، وكل الروابط بيتزاروا بالتوازي (تبويبات متعددة مع بعض)
    بدل التتابع - الوقت الكلي بقى أقرب لأبطأ صفحة لوحدها مش مجموع كل الصفحات،
    مع حد أقصى MAX_CONCURRENT_PAGES تبويب في نفس اللحظة."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_PAGES)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            tasks = [_fetch_one_page(browser, url, semaphore) for url in urls]
            results = await asyncio.gather(*tasks)
        finally:
            await browser.close()
    return list(results)


def fetch_multiple_pages(urls: list[str]) -> list[PageContent]:
    """نفس الشكل والاستخدام القديم بالظبط (sync)، لكن جواها بقت بتزور كل
    الروابط بالتوازي بدل التتابع. مفيش أي تغيير مطلوب في الكود اللي بينادي
    عليها (api.py وغيره).

    بنسجل الزمن الكلي في اللوج كإثبات تشغيلي إن الروابط بتتزار بالتوازي:
    لو كان تتابعي هيبقى الزمن ≈ مجموع أزمنة كل الروابط، وبالتوازي هيبقى
    قريب من أبطأ رابط لوحده (± overhead فتح التبويبات)."""
    started = time.monotonic()
    results = asyncio.run(_fetch_multiple_pages_async(urls))
    elapsed = time.monotonic() - started
    log.info(
        f"fetch_multiple_pages: {len(urls)} رابط في {elapsed:.1f}s "
        f"(متوازي، حد أقصى {MAX_CONCURRENT_PAGES} تبويب مع بعض)"
    )
    return results