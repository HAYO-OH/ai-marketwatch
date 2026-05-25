from tavily import TavilyClient as _TavilyClient
from config.settings import settings


class TavilyClient:
    def __init__(self):
        self.client = _TavilyClient(api_key=settings.tavily_api_key)

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        result = self.client.search(query=query, max_results=max_results)
        return result.get("results", [])
