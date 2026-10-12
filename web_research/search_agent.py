"""
Search Agent
=============
واجهة بحث بمزودين: SerpAPI (أساسي، زي ما هو مذكور في مستند التخطيط الأصلي)
و Tavily (fallback تلقائي لو SerpAPI فشل أو مفتاحه غير موجود).

النتيجة النهائية (SearchResult) موحّدة الشكل بغض النظر عن مين اللي فعليًا رد،
عشان الـ Browser Agent يفضل يشتغل من غير ما يعرف مين المزود.
"""

from __future__ import annotations

from dataclasses import dataclass

from serpapi import GoogleSearch
from tavily import TavilyClient

from shared.config import settings
from shared.logger import get_logger

log = get_logger("web_research.search_agent")


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str
    score: float | None = None


def _search_serpapi(query: str, max_results: int) -> list[SearchResult]:
    if not settings.serpapi_key:
        raise EnvironmentError("SERPAPI_KEY مش موجود في .env")

    log.info(f"بحث SerpAPI عن: '{query}' (max_results={max_results})")
    params = {
        "engine": "google",
        "q": query,
        "api_key": settings.serpapi_key,
        "num": max_results,
    }
    search = GoogleSearch(params)
    response = search.get_dict()

    if "error" in response:
        raise RuntimeError(f"خطأ من SerpAPI: {response['error']}")

    organic = response.get("organic_results", [])[:max_results]
    results = [
        SearchResult(
            url=item.get("link", ""),
            title=item.get("title", ""),
            snippet=item.get("snippet", ""),
            score=None,  # SerpAPI مش بيرجع score صريح زي Tavily
        )
        for item in organic
        if item.get("link")
    ]
    log.info(f"SerpAPI رجع {len(results)} نتيجة")
    return results


def _search_tavily(query: str, max_results: int) -> list[SearchResult]:
    if not settings.tavily_api_key:
        raise EnvironmentError("TAVILY_API_KEY مش موجود في .env")

    log.info(f"بحث Tavily (fallback) عن: '{query}' (max_results={max_results})")
    client = TavilyClient(api_key=settings.tavily_api_key)
    response = client.search(query=query, max_results=max_results, search_depth="advanced")

    results = [
        SearchResult(
            url=item["url"],
            title=item.get("title", ""),
            snippet=item.get("content", ""),
            score=item.get("score"),
        )
        for item in response.get("results", [])
    ]
    log.info(f"Tavily رجع {len(results)} نتيجة")
    return results


def search_topic(query: str, max_results: int = 5) -> list[SearchResult]:
    """
    يرجع أهم النتائج لموضوع بحث معين. SerpAPI أولًا؛ لو فشل (مفتاح ناقص،
    خطأ في الـ API، أو استثناء أي نوع) بيقع تلقائيًا على Tavily بدل ما
    يفشل الطلب كله.
    """
    try:
        results = _search_serpapi(query, max_results)
        if results:
            return results
        log.warning("SerpAPI رجع نتيجة فاضية، بنجرب Tavily كـ fallback")
    except Exception as e:  # noqa: BLE001 — أي فشل من SerpAPI يوديني على fallback
        log.warning(f"SerpAPI فشل، بنجرب Tavily كـ fallback: {e}")

    return _search_tavily(query, max_results)