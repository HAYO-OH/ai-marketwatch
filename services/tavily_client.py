from email.utils import parsedate
from tavily import TavilyClient as _TavilyClient
from config.settings import settings


def _parse_pub_date(raw: str) -> str:
    """RFC 2822 또는 ISO 날짜 문자열을 YYYY-MM-DD로 변환."""
    if not raw:
        return ""
    try:
        t = parsedate(raw)
        if t:
            return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}"
    except Exception:
        pass
    # ISO 형식 fallback
    return raw[:10] if len(raw) >= 10 and raw[4] == "-" else ""


class TavilyClient:
    def __init__(self):
        self.client = _TavilyClient(api_key=settings.tavily_api_key)

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        result = self.client.search(query=query, max_results=max_results)
        return result.get("results", [])

    def get_news(self, corp_name: str, days: int = 30, max_results: int = 20) -> list[dict]:
        result = self.client.search(
            query=f"{corp_name} 주식",
            max_results=max_results,
            topic="news",
            days=days,
        )
        articles = []
        for r in result.get("results", []):
            title = r.get("title", "").strip()
            if title:
                articles.append({
                    "title": title,
                    "content": r.get("content", "").strip()[:300],
                    "published_date": _parse_pub_date(r.get("published_date", "")),
                })
        return articles
