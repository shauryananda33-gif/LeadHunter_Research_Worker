from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from playwright.async_api import Browser, Page, async_playwright

logger = logging.getLogger(__name__)

GOOGLE_HOSTS = {
    "google.com",
    "www.google.com",
    "google.co.in",
    "www.google.co.in",
}

BLOCK_MARKERS = (
    "our systems have detected unusual traffic",
    "unusual traffic from your computer network",
    "not a robot",
    "captcha",
    "/sorry/",
    "recaptcha",
)

SKIP_HOSTS = {
    "google.com",
    "www.google.com",
    "google.co.in",
    "www.google.co.in",
    "gstatic.com",
    "www.gstatic.com",
    "googleusercontent.com",
    "www.googleusercontent.com",
}

SKIP_TITLE_PATTERNS = (
    "images",
    "videos",
    "news",
    "maps",
    "shopping",
    "books",
    "flights",
)


class SERPError(Exception):
    """Raised when a SERP cannot be retrieved or parsed."""


@dataclass
class SERPResult:
    rank: int
    title: str
    url: str
    domain: str
    snippet: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "title": self.title,
            "url": self.url,
            "domain": self.domain,
            "snippet": self.snippet,
        }


class GoogleSERPScraper:
    def __init__(self) -> None:
        self.logger = logger

    async def search(
        self,
        query: str,
        location: str | None = None,
        country: str = "in",
        language: str = "en",
        max_results: int = 10,
    ) -> dict[str, Any]:
        search_query = " ".join(
            part.strip()
            for part in (query, location)
            if part and part.strip()
        )

        url = (
            "https://www.google.com/search"
            f"?q={__import__('urllib.parse').parse.quote_plus(search_query)}"
            f"&hl={language}&gl={country}&num=100&filter=0"
        )

        self.logger.info("Opening Google SERP: %s", url)

        async with async_playwright() as pw:
            browser: Browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--no-zygote",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            try:
                context = await browser.new_context(
                    locale=f"{language}-{country.upper()}",
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    extra_http_headers={
                        "Accept-Language": f"{language}-{country.upper()},{language};q=0.9"
                    },
                    viewport={"width": 1365, "height": 900},
                )

                page = await context.new_page()
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=45000,
                )

                status = response.status if response else None
                self.logger.info("Google response status: %s", status)

                await page.wait_for_timeout(2500)

                html = await page.content()
                text = await page.locator("body").inner_text(timeout=10000)

                self._check_for_block(html, text, str(page.url))

                results = await self._extract_results(page)

                if not results:
                    preview = re.sub(r"\s+", " ", html[:1800])
                    self.logger.warning(
                        "No organic results extracted. HTML preview: %s",
                        preview,
                    )
                    raise SERPError(
                        "No organic Google results could be extracted."
                    )

                results = results[:max_results]

                return {
                    "ok": True,
                    "query": query,
                    "location": location,
                    "country": country,
                    "language": language,
                    "result_count": len(results),
                    "results": [item.as_dict() for item in results],
                }

            finally:
                await browser.close()

    def _check_for_block(
        self,
        html: str,
        text: str,
        current_url: str,
    ) -> None:
        combined = f"{current_url}\n{text}\n{html}".lower()

        for marker in BLOCK_MARKERS:
            if marker in combined:
                raise SERPError(
                    f"Google returned a challenge/block page ({marker})."
                )

    async def _extract_results(self, page: Page) -> list[SERPResult]:
        # Google changes its markup frequently. Rather than depending on one
        # class name, collect likely result blocks and use several fallbacks.
        selectors = [
            "div.MjjYud",
            "div[data-snhf]",
            "div[data-hveid]",
            "div#search div",
        ]

        candidates: list[Any] = []
        seen_nodes: set[int] = set()

        for selector in selectors:
            try:
                loc = page.locator(selector)
                count = await loc.count()
                self.logger.info(
                    "Selector %s returned %d candidates", selector, count
                )

                for i in range(min(count, 250)):
                    node = loc.nth(i)
                    key = id(node)
                    if key not in seen_nodes:
                        seen_nodes.add(key)
                        candidates.append(node)
            except Exception as exc:
                self.logger.debug(
                    "Selector failed %s: %s", selector, exc
                )

        self.logger.info("Potential result containers found: %d", len(candidates))

        parsed: list[SERPResult] = []
        seen_urls: set[str] = set()

        for node in candidates:
            try:
                item = await self._parse_candidate(node)
                if not item:
                    continue

                normalized = self._normalize_url(item["url"])
                if not normalized:
                    continue

                domain = (urlparse(normalized).hostname or "").lower()
                if self._skip_domain(domain):
                    continue

                title = self._clean_text(item["title"])
                snippet = self._clean_text(item["snippet"])

                if not title:
                    continue

                # Avoid Google navigation/category blocks.
                if self._skip_title(title):
                    continue

                if normalized in seen_urls:
                    continue

                seen_urls.add(normalized)

                parsed.append(
                    SERPResult(
                        rank=len(parsed) + 1,
                        title=title,
                        url=normalized,
                        domain=domain.removeprefix("www."),
                        snippet=snippet,
                    )
                )

                if len(parsed) >= 100:
                    break

            except Exception as exc:
                self.logger.debug("Candidate parse failed: %s", exc)

        # Final fallback: inspect all links in the search area and reconstruct
        # result records when Google's container structure is unusual.
        if not parsed:
            parsed = await self._extract_from_links(page)

        self.logger.info("Organic results extracted: %d", len(parsed))
        return parsed

    async def _parse_candidate(self, node: Any) -> dict[str, str] | None:
        links = await node.locator("a[href]").all()

        valid_links: list[tuple[str, str]] = []
        for link in links:
            href = await link.get_attribute("href")
            if not href:
                continue

            normalized = self._normalize_url(href)
            if not normalized:
                continue

            domain = (urlparse(normalized).hostname or "").lower()
            if self._skip_domain(domain):
                continue

            text = self._clean_text(await link.inner_text())
            if text:
                valid_links.append((normalized, text))

        if not valid_links:
            return None

        url, anchor_text = max(
            valid_links,
            key=lambda pair: len(pair[1]),
        )

        title = ""
        for selector in (
            "h3",
            "h2",
            "[role='heading']",
            "div[role='heading']",
        ):
            try:
                loc = node.locator(selector)
                count = await loc.count()
                if count:
                    title = self._clean_text(await loc.first.inner_text())
                    if title:
                        break
            except Exception:
                pass

        if not title:
            title = anchor_text

        snippet = ""
        for selector in (
            "div.VwiC3b",
            "div[data-sncf]",
            "span.aCOpRe",
            "div[style*='-webkit-line-clamp']",
            "[data-content-feature='1']",
        ):
            try:
                loc = node.locator(selector)
                count = await loc.count()
                if count:
                    snippet = self._clean_text(await loc.first.inner_text())
                    if snippet:
                        break
            except Exception:
                pass

        if not snippet:
            try:
                text = self._clean_text(await node.inner_text())
                if text and text != title:
                    parts = [p.strip() for p in text.split("\n") if p.strip()]
                    remaining = [
                        p for p in parts
                        if p.lower() != title.lower()
                    ]
                    snippet = " ".join(remaining[:3])
            except Exception:
                pass

        return {
            "title": title,
            "url": url,
            "snippet": snippet,
        }

    async def _extract_from_links(self, page: Page) -> list[SERPResult]:
        self.logger.info("Using link-based fallback extraction")

        try:
            search_area = page.locator("#search")
            links = search_area.locator("a[href]")
            count = await links.count()
        except Exception:
            return []

        results: list[SERPResult] = []
        seen_urls: set[str] = set()

        for i in range(min(count, 500)):
            try:
                link = links.nth(i)
                href = await link.get_attribute("href")
                if not href:
                    continue

                normalized = self._normalize_url(href)
                if not normalized:
                    continue

                domain = (urlparse(normalized).hostname or "").lower()
                if self._skip_domain(domain):
                    continue

                title = self._clean_text(await link.inner_text())
                if not title or len(title) < 2:
                    continue

                if self._skip_title(title):
                    continue

                if normalized in seen_urls:
                    continue

                # A normal organic result link generally has a nearby heading.
                # Prefer h3 text where available.
                title_loc = link.locator("xpath=ancestor::*[self::div][1]//h3")
                try:
                    if await title_loc.count():
                        candidate_title = self._clean_text(
                            await title_loc.first.inner_text()
                        )
                        if candidate_title:
                            title = candidate_title
                except Exception:
                    pass

                seen_urls.add(normalized)

                results.append(
                    SERPResult(
                        rank=len(results) + 1,
                        title=title,
                        url=normalized,
                        domain=domain.removeprefix("www."),
                        snippet="",
                    )
                )

                if len(results) >= 100:
                    break

            except Exception as exc:
                self.logger.debug(
                    "Link fallback candidate failed: %s", exc
                )

        return results

    @staticmethod
    def _normalize_url(href: str) -> str | None:
        href = href.strip()

        if href.startswith("//"):
            href = "https:" + href

        if href.startswith("/url?"):
            parsed = urlparse(href)
            target = parse_qs(parsed.query).get("q", [])
            if target:
                href = unquote(target[0])

        parsed = urlparse(href)

        if parsed.scheme not in {"http", "https"}:
            return None

        if not parsed.hostname:
            return None

        # Strip tracking fragments and common Google redirect parameters.
        clean = parsed._replace(fragment="").geturl()

        if "google." in (parsed.hostname or "").lower():
            return None

        return clean

    @staticmethod
    def _skip_domain(domain: str) -> bool:
        domain = domain.lower().removeprefix("www.")
        return (
            not domain
            or domain in {host.removeprefix("www.") for host in SKIP_HOSTS}
            or domain.endswith(".google.com")
            or domain.endswith(".google.co.in")
            or domain.endswith(".gstatic.com")
        )

    @staticmethod
    def _skip_title(title: str) -> bool:
        lowered = title.strip().lower()
        if not lowered:
            return True

        if lowered in {"more results", "see more", "sign in"}:
            return True

        return any(
            lowered == pattern
            or lowered.startswith(pattern + " ")
            for pattern in SKIP_TITLE_PATTERNS
        )

    @staticmethod
    def _clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", value or "").strip()
