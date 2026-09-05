from __future__ import annotations
import logging, os, re
from dataclasses import dataclass
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class SearchError(Exception):
    pass

@dataclass
class SearchResult:
    rank: int
    title: str
    url: str
    domain: str
    snippet: str
    def as_dict(self):
        return {"rank": self.rank, "title": self.title, "url": self.url,
                "domain": self.domain, "snippet": self.snippet}

class SearXNGClient:
    DEFAULT_URL = "https://searx.tiekoetter.com"

    def __init__(self):
        self.base_url = os.getenv("SEARXNG_URL", self.DEFAULT_URL).rstrip("/")
        self.timeout = float(os.getenv("SEARXNG_TIMEOUT", "20"))
        self.user_agent = "LeadHunterResearchWorker/0.2 (self-hosted search client)"

    async def search(self, query, location=None, country="in",
                     language="en", max_results=10):
        search_query = " ".join(x.strip() for x in (query, location or "") if x and x.strip())
        lang = self._language(language, country)
        logger.info("SearXNG search: backend=%s query=%r", self.base_url, search_query)

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True,
                                     headers={"User-Agent": self.user_agent}) as http:
            params = {"q": search_query, "format": "json", "language": lang,
                      "safesearch": "0", "pageno": "1"}
            try:
                response = await http.get(f"{self.base_url}/search", params=params,
                                          headers={"Accept": "application/json"})
            except httpx.HTTPError as exc:
                raise SearchError(f"SearXNG connection failed: {exc}") from exc

            logger.info("SearXNG JSON response status: %s", response.status_code)
            if response.status_code == 200:
                try:
                    results = self._parse_json(response.json(), max_results)
                    if results:
                        return self._response(query, location, country, language,
                                              results, "json")
                except ValueError:
                    logger.warning("SearXNG returned non-JSON content")

            results = await self._html_fallback(http, search_query, lang, max_results)
            if results:
                return self._response(query, location, country, language,
                                      results, "html")

            raise SearchError(
                f"SearXNG returned no usable search results (HTTP {response.status_code})."
            )

    async def _html_fallback(self, http, search_query, language, max_results):
        try:
            response = await http.get(
                f"{self.base_url}/search",
                params={"q": search_query, "language": language,
                        "safesearch": "0", "pageno": "1"},
                headers={"Accept": "text/html"})
        except httpx.HTTPError as exc:
            logger.warning("SearXNG HTML fallback failed: %s", exc)
            return []
        logger.info("SearXNG HTML fallback status: %s", response.status_code)
        if response.status_code != 200:
            return []
        return self._parse_html(response.text, max_results)

    def _parse_json(self, payload, max_results):
        raw = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            return []
        out, seen = [], set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            title = self._clean(item.get("title"))
            url = self._normalize_url(item.get("url"))
            snippet = self._clean(item.get("content") or item.get("snippet") or "")
            if not title or not url:
                continue
            domain = self._domain(url)
            if not domain or self._skip_domain(domain) or url in seen:
                continue
            seen.add(url)
            out.append(SearchResult(len(out)+1, title, url, domain, snippet))
            if len(out) >= max_results:
                break
        return out

    def _parse_html(self, html, max_results):
        soup = BeautifulSoup(html, "html.parser")
        nodes = []
        for selector in ("article.result", "div.result", ".result", "article[data-result]"):
            nodes.extend(soup.select(selector))
        out, seen = [], set()
        for node in nodes:
            anchor = node.select_one("h3 a[href], h4 a[href], a.result_header[href], a[href]")
            if not anchor:
                continue
            title = self._clean(anchor.get_text(" ", strip=True))
            url = self._normalize_url(anchor.get("href"))
            if not title or not url:
                continue
            domain = self._domain(url)
            if not domain or self._skip_domain(domain) or url in seen:
                continue
            snippet_node = node.select_one(".content, .result-content, .snippet")
            snippet = self._clean(snippet_node.get_text(" ", strip=True) if snippet_node else "")
            seen.add(url)
            out.append(SearchResult(len(out)+1, title, url, domain, snippet))
            if len(out) >= max_results:
                break
        return out

    @staticmethod
    def _response(query, location, country, language, results, source_format):
        return {"ok": True, "query": query, "location": location, "country": country,
                "language": language, "backend": "searxng",
                "source_format": source_format, "result_count": len(results),
                "results": [r.as_dict() for r in results]}

    @staticmethod
    def _language(language, country):
        language, country = language.strip().lower(), country.strip().upper()
        return f"en-{country}" if language == "en" and country else (language or "all")

    @staticmethod
    def _normalize_url(value):
        if not value:
            return None
        value = str(value).strip()
        if value.startswith("//"):
            value = "https:" + value
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        return parsed._replace(fragment="").geturl()

    @staticmethod
    def _domain(url):
        return (urlparse(url).hostname or "").lower().removeprefix("www.")

    @staticmethod
    def _skip_domain(domain):
        domain = domain.lower().removeprefix("www.")
        blocked = {"google.com", "google.co.in", "gstatic.com",
                   "bing.com", "duckduckgo.com", "searx.tiekoetter.com"}
        return (not domain or domain in blocked or domain.endswith(".google.com")
                or domain.endswith(".google.co.in") or domain.endswith(".gstatic.com"))

    @staticmethod
    def _clean(value):
        return re.sub(r"\s+", " ", str(value or "")).strip()
