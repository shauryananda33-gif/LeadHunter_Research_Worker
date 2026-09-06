from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("leadhunter-searxng-client")


class SearchError(Exception):
    """Raised when the SearXNG backend cannot produce usable results."""


@dataclass(frozen=True)
class SearchResult:
    rank: int
    title: str
    url: str
    domain: str
    snippet: str

    def as_dict(self) -> dict[str, object]:
        return {"rank": self.rank, "title": self.title, "url": self.url, "domain": self.domain, "snippet": self.snippet}


class SearXNGClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("SEARXNG_URL", "").strip().rstrip("/")
        self.timeout = float(os.getenv("SEARXNG_TIMEOUT", "25"))
        self.auth_user = os.getenv("SEARXNG_AUTH_USER", "").strip()
        self.auth_password = os.getenv("SEARXNG_AUTH_PASSWORD", "")
        self.user_agent = "LeadHunterResearchWorker/0.5.0"

    def validate_config(self) -> None:
        if not self.base_url:
            raise SearchError("SEARXNG_URL is not configured.")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise SearchError("SEARXNG_URL must be a valid http(s) URL.")
        if bool(self.auth_user) != bool(self.auth_password):
            raise SearchError("SEARXNG_AUTH_USER and SEARXNG_AUTH_PASSWORD must be set together.")

    @staticmethod
    def _language(language: str, country: str) -> str:
        language, country = language.strip().lower(), country.strip().upper()
        return f"en-{country}" if language == "en" and country else (language or "all")

    @staticmethod
    def _clean(value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @staticmethod
    def _normalize_url(value: object) -> str | None:
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
    def _domain(url: str) -> str:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")

    @staticmethod
    def _blocked(domain: str) -> bool:
        domain = domain.lower().removeprefix("www.")
        blocked = {"google.com", "google.co.in", "bing.com", "duckduckgo.com", "gstatic.com"}
        return not domain or domain in blocked or domain.endswith(".google.com") or domain.endswith(".google.co.in") or domain.endswith(".gstatic.com")

    def _parse(self, payload: object, max_results: int) -> list[SearchResult]:
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            return []
        results: list[SearchResult] = []
        seen: set[str] = set()
        for item in payload["results"]:
            if not isinstance(item, dict):
                continue
            title = self._clean(item.get("title"))
            url = self._normalize_url(item.get("url"))
            snippet = self._clean(item.get("content") or item.get("snippet"))
            if not title or not url or url in seen:
                continue
            domain = self._domain(url)
            if self._blocked(domain):
                continue
            seen.add(url)
            results.append(SearchResult(len(results) + 1, title, url, domain, snippet))
            if len(results) >= max_results:
                break
        return results

    async def search(self, query: str, location: str | None = None, country: str = "in", language: str = "en", max_results: int = 10) -> dict[str, object]:
        self.validate_config()
        search_query = " ".join(part.strip() for part in (query, location or "") if part and part.strip())
        params = {"q": search_query, "format": "json", "language": self._language(language, country), "safesearch": "0", "pageno": "1"}
        auth = httpx.BasicAuth(self.auth_user, self.auth_password) if self.auth_user else None
        logger.info("SearXNG search backend=%s query=%r", self.base_url, search_query)
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, auth=auth, headers={"User-Agent": self.user_agent}) as http:
                response = await http.get(f"{self.base_url}/search", params=params, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise SearchError(f"SearXNG connection failed: {exc}") from exc
        if response.status_code != 200:
            raise SearchError(f"SearXNG returned HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise SearchError("SearXNG returned invalid JSON.") from exc
        results = self._parse(payload, max_results)
        if not results:
            raise SearchError("SearXNG returned no usable search results.")
        return {"ok": True, "query": query, "location": location, "country": country, "language": language, "backend": "searxng", "result_count": len(results), "results": [result.as_dict() for result in results]}
