from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="LeadHunter Research Worker",
    version="0.2.1",
    description="Standalone research worker for LeadHunter.",
)

SEARXNG_URL = os.getenv(
    "SEARXNG_URL",
    "https://searx.tiekoetter.com",
).rstrip("/")

SEARXNG_TIMEOUT = float(
    os.getenv("SEARXNG_TIMEOUT", "20")
)

USER_AGENT = "LeadHunterResearchWorker/0.2.1"


class SearchError(Exception):
    pass


@dataclass
class SearchResult:
    rank: int
    title: str
    url: str
    domain: str
    snippet: str

    def as_dict(self) -> dict:
        return {
            "rank": self.rank,
            "title": self.title,
            "url": self.url,
            "domain": self.domain,
            "snippet": self.snippet,
        }


class SERPRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    location: str | None = Field(default=None, max_length=150)
    country: str = Field(default="in", min_length=2, max_length=10)
    language: str = Field(default="en", min_length=2, max_length=10)
    max_results: int = Field(default=10, ge=1, le=50)


def clean_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_url(value) -> str | None:
    if not value:
        return None

    value = str(value).strip()

    if value.startswith("//"):
        value = "https:" + value

    parsed = urlparse(value)

    if parsed.scheme not in {"http", "https"}:
        return None

    if not parsed.hostname:
        return None

    return parsed._replace(fragment="").geturl()


def domain_for(url: str) -> str:
    return (
        urlparse(url).hostname or ""
    ).lower().removeprefix("www.")


def skip_domain(domain: str) -> bool:
    domain = domain.lower().removeprefix("www.")

    blocked = {
        "google.com",
        "google.co.in",
        "gstatic.com",
        "bing.com",
        "duckduckgo.com",
        "searx.tiekoetter.com",
    }

    return (
        not domain
        or domain in blocked
        or domain.endswith(".google.com")
        or domain.endswith(".google.co.in")
        or domain.endswith(".gstatic.com")
    )


def language_code(language: str, country: str) -> str:
    language = language.strip().lower()
    country = country.strip().upper()

    if language == "en" and country:
        return f"en-{country}"

    return language or "all"


def parse_json_results(payload: dict, max_results: int) -> list[SearchResult]:
    raw_results = payload.get("results")

    if not isinstance(raw_results, list):
        return []

    results: list[SearchResult] = []
    seen: set[str] = set()

    for item in raw_results:
        if not isinstance(item, dict):
            continue

        title = clean_text(item.get("title"))
        url = normalize_url(item.get("url"))
        snippet = clean_text(
            item.get("content")
            or item.get("snippet")
            or ""
        )

        if not title or not url:
            continue

        domain = domain_for(url)

        if skip_domain(domain) or url in seen:
            continue

        seen.add(url)

        results.append(
            SearchResult(
                rank=len(results) + 1,
                title=title,
                url=url,
                domain=domain,
                snippet=snippet,
            )
        )

        if len(results) >= max_results:
            break

    return results


def parse_html_results(html: str, max_results: int) -> list[SearchResult]:
    soup = BeautifulSoup(html, "html.parser")

    nodes = []

    for selector in (
        "article.result",
        "div.result",
        ".result",
        "article[data-result]",
    ):
        nodes.extend(soup.select(selector))

    results: list[SearchResult] = []
    seen: set[str] = set()

    for node in nodes:
        anchor = node.select_one(
            "h3 a[href], h4 a[href], a.result_header[href], a[href]"
        )

        if not anchor:
            continue

        title = clean_text(anchor.get_text(" ", strip=True))
        url = normalize_url(anchor.get("href"))

        if not title or not url:
            continue

        domain = domain_for(url)

        if skip_domain(domain) or url in seen:
            continue

        snippet_node = node.select_one(
            ".content, .result-content, .snippet"
        )

        snippet = clean_text(
            snippet_node.get_text(" ", strip=True)
            if snippet_node
            else ""
        )

        seen.add(url)

        results.append(
            SearchResult(
                rank=len(results) + 1,
                title=title,
                url=url,
                domain=domain,
                snippet=snippet,
            )
        )

        if len(results) >= max_results:
            break

    return results


async def search_serp(
    query: str,
    location: str | None,
    country: str,
    language: str,
    max_results: int,
) -> dict:
    search_query = " ".join(
        part.strip()
        for part in (query, location or "")
        if part and part.strip()
    )

    lang = language_code(language, country)

    logger.info(
        "SearXNG search: backend=%s query=%r language=%s",
        SEARXNG_URL,
        search_query,
        lang,
    )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }

    params = {
        "q": search_query,
        "format": "json",
        "language": lang,
        "safesearch": "0",
        "pageno": "1",
    }

    async with httpx.AsyncClient(
        timeout=SEARXNG_TIMEOUT,
        follow_redirects=True,
    ) as http:
        try:
            response = await http.get(
                f"{SEARXNG_URL}/search",
                params=params,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise SearchError(
                f"SearXNG connection failed: {exc}"
            ) from exc

        logger.info(
            "SearXNG JSON response: HTTP %s content-type=%s",
            response.status_code,
            response.headers.get("content-type", ""),
        )

        results: list[SearchResult] = []

        if response.status_code == 200:
            try:
                payload = response.json()
                results = parse_json_results(
                    payload,
                    max_results,
                )
            except ValueError:
                logger.warning(
                    "SearXNG response was not valid JSON"
                )

        if not results:
            logger.info(
                "Trying SearXNG HTML fallback"
            )

            html_params = {
                "q": search_query,
                "language": lang,
                "safesearch": "0",
                "pageno": "1",
            }

            try:
                html_response = await http.get(
                    f"{SEARXNG_URL}/search",
                    params=html_params,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": "text/html",
                    },
                )
            except httpx.HTTPError as exc:
                raise SearchError(
                    f"SearXNG HTML fallback failed: {exc}"
                ) from exc

            logger.info(
                "SearXNG HTML response: HTTP %s",
                html_response.status_code,
            )

            if html_response.status_code == 200:
                results = parse_html_results(
                    html_response.text,
                    max_results,
                )

        if not results:
            raise SearchError(
                "SearXNG returned no usable search results."
            )

        return {
            "ok": True,
            "query": query,
            "location": location,
            "country": country,
            "language": language,
            "backend": "searxng",
            "backend_url": SEARXNG_URL,
            "result_count": len(results),
            "results": [
                result.as_dict()
                for result in results
            ],
        }


@app.get("/")
async def root():
    return {
        "ok": True,
        "service": "leadhunter-research-worker",
        "version": "0.2.1",
        "search_backend": "searxng",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "leadhunter-research-worker",
        "status": "healthy",
        "search_backend": "searxng",
    }


@app.post("/serp")
async def serp(request: SERPRequest):
    try:
        return await search_serp(
            query=request.query.strip(),
            location=request.location,
            country=request.country,
            language=request.language,
            max_results=request.max_results,
        )
    except SearchError as exc:
        logger.warning("SERP search failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc
    except Exception:
        logger.exception("Unexpected SERP worker failure")
        raise HTTPException(
            status_code=500,
            detail="SERP worker failed unexpectedly",
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000")),
    )
