import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


logger = logging.getLogger("leadhunter-serp")


class SERPError(Exception):
    """Raised when Google SERP collection fails."""


class GoogleSERPScraper:
    """
    Small, isolated Google organic SERP scraper.

    This worker intentionally focuses on organic search results.
    Google Maps / GBP research is handled separately later.
    """

    GOOGLE_URL = "https://www.google.com/search"

    USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        timeout_ms: int = 30000,
        navigation_timeout_ms: int = 30000,
        pause_seconds: float = 1.0,
    ):
        self.timeout_ms = timeout_ms
        self.navigation_timeout_ms = navigation_timeout_ms
        self.pause_seconds = max(0.0, pause_seconds)

    def search(
        self,
        query: str,
        location: Optional[str] = None,
        country: str = "in",
        language: str = "en",
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        query = query.strip()

        if not query:
            raise SERPError("Search query is empty.")

        if max_results < 1:
            raise SERPError("max_results must be at least 1.")

        if max_results > 50:
            max_results = 50

        playwright: Optional[Playwright] = None
        browser: Optional[Browser] = None
        context: Optional[BrowserContext] = None

        try:
            playwright = sync_playwright().start()

            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            context = browser.new_context(
                user_agent=self.USER_AGENT,
                locale=language,
                viewport={
                    "width": 1366,
                    "height": 900,
                },
                extra_http_headers={
                    "Accept-Language": f"{language}-{country.upper()},{language};q=0.9",
                },
            )

            page = context.new_page()

            page.set_default_timeout(self.timeout_ms)
            page.set_default_navigation_timeout(
                self.navigation_timeout_ms
            )

            url = self._build_search_url(
                query=query,
                country=country,
                language=language,
                location=location,
            )

            logger.info("Opening Google SERP: %s", url)

            response = page.goto(
                url,
                wait_until="domcontentloaded",
            )

            if response is None:
                raise SERPError("Google returned no navigation response.")

            status = response.status

            logger.info("Google response status: %s", status)

            if status >= 400:
                raise SERPError(
                    f"Google search returned HTTP status {status}."
                )

            self._wait_for_results(page)

            if self._looks_blocked(page):
                raise SERPError(
                    "Google appears to have blocked or challenged the request."
                )

            if self.pause_seconds:
                time.sleep(self.pause_seconds)

            results = self._extract_results(
                page=page,
                max_results=max_results,
            )

            if not results:
                html_preview = page.content()[:1000]

                logger.warning(
                    "No organic results extracted. HTML preview: %s",
                    html_preview,
                )

                raise SERPError(
                    "No organic Google results could be extracted."
                )

            return results

        except PlaywrightTimeoutError as exc:
            raise SERPError(
                f"Google search timed out: {exc}"
            ) from exc

        except SERPError:
            raise

        except Exception as exc:
            raise SERPError(
                f"SERP collection failed: {exc}"
            ) from exc

        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass

            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    pass

    def _build_search_url(
        self,
        query: str,
        country: str,
        language: str,
        location: Optional[str],
    ) -> str:
        """
        Build Google search URL.

        Location is supplied through Google's `uule`/location mechanisms
        only when we have a reliable implementation. For this first
        worker version we keep the location in the query when supplied.

        Example:
        "dentist Indore"
        """

        from urllib.parse import urlencode

        effective_query = query

        if location:
            effective_query = f"{query} {location.strip()}"

        params = {
            "q": effective_query,
            "hl": language,
            "gl": country,
            "num": "100",
            "filter": "0",
        }

        return f"{self.GOOGLE_URL}?{urlencode(params)}"

    def _wait_for_results(self, page: Page) -> None:
        selectors = [
            "div#search",
            "div.MjjYud",
            "div.g",
            "body",
        ]

        for selector in selectors:
            try:
                page.wait_for_selector(
                    selector,
                    state="visible",
                    timeout=8000,
                )
                return
            except PlaywrightTimeoutError:
                continue

    def _looks_blocked(self, page: Page) -> bool:
        try:
            title = (page.title() or "").lower()
        except Exception:
            title = ""

        try:
            body = page.locator("body").inner_text(
                timeout=5000
            ).lower()
        except Exception:
            body = ""

        blocked_phrases = [
            "unusual traffic",
            "our systems have detected unusual traffic",
            "captcha",
            "recaptcha",
            "sorry, but your computer or network may be sending",
        ]

        combined = f"{title}\n{body}"

        return any(
            phrase in combined
            for phrase in blocked_phrases
        )

    def _extract_results(
        self,
        page: Page,
        max_results: int,
    ) -> List[Dict[str, Any]]:
        """
        Extract organic results.

        We intentionally avoid relying on only one Google CSS class.
        Google changes markup frequently.
        """

        results: List[Dict[str, Any]] = []

        containers = page.locator(
            "div#search div.MjjYud"
        )

        count = containers.count()

        logger.info(
            "Potential result containers found: %s",
            count,
        )

        for index in range(count):
            if len(results) >= max_results:
                break

            container = containers.nth(index)

            try:
                parsed = self._parse_result_container(
                    container=container,
                )

                if parsed is None:
                    continue

                if not self._is_valid_result(parsed):
                    continue

                parsed["rank"] = len(results) + 1

                results.append(parsed)

            except Exception as exc:
                logger.debug(
                    "Skipping SERP container %s: %s",
                    index,
                    exc,
                )

        return results

    def _parse_result_container(
        self,
        container,
    ) -> Optional[Dict[str, Any]]:
        """
        Parse a likely organic result.
        """

        links = container.locator("a")

        link_count = links.count()

        candidate_url = None
        title = None

        for i in range(min(link_count, 15)):
            link = links.nth(i)

            try:
                href = link.get_attribute("href")

                if not href:
                    continue

                href = href.strip()

                if not href.startswith("http"):
                    continue

                if self._is_google_internal_url(href):
                    continue

                text = link.inner_text().strip()

                if len(text) < 2:
                    continue

                candidate_url = href
                title = text

                break

            except Exception:
                continue

        if not candidate_url or not title:
            return None

        domain = self._extract_domain(candidate_url)

        if not domain:
            return None

        snippet = self._extract_snippet(container)

        display_domain = domain

        return {
            "title": self._clean_text(title),
            "url": candidate_url,
            "domain": display_domain,
            "snippet": snippet,
        }

    def _extract_snippet(self, container) -> Optional[str]:
        selectors = [
            "div.VwiC3b",
            "div[data-sncf]",
            "span.aCOpRe",
        ]

        for selector in selectors:
            try:
                locator = container.locator(selector)

                if locator.count() == 0:
                    continue

                text = locator.first.inner_text().strip()

                if text:
                    return self._clean_text(text)

            except Exception:
                continue

        return None

    def _is_valid_result(
        self,
        result: Dict[str, Any],
    ) -> bool:
        url = result.get("url", "")
        title = result.get("title", "")

        if not url or not title:
            return False

        parsed = urlparse(url)

        if parsed.scheme not in {
            "http",
            "https",
        }:
            return False

        domain = parsed.netloc.lower()

        ignored_domains = {
            "google.com",
            "www.google.com",
            "google.co.in",
            "www.google.co.in",
        }

        if domain in ignored_domains:
            return False

        ignored_title_patterns = [
            r"^images?$",
            r"^videos?$",
            r"^maps?$",
            r"^news$",
        ]

        for pattern in ignored_title_patterns:
            if re.search(pattern, title, flags=re.I):
                return False

        return True

    def _is_google_internal_url(
        self,
        url: str,
    ) -> bool:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            return (
                "google." in domain
                or domain.endswith("googleusercontent.com")
            )

        except Exception:
            return True

    def _extract_domain(
        self,
        url: str,
    ) -> Optional[str]:
        try:
            parsed = urlparse(url)

            hostname = parsed.hostname

            if not hostname:
                return None

            hostname = hostname.lower()

            if hostname.startswith("www."):
                hostname = hostname[4:]

            return hostname

        except Exception:
            return None

    def _clean_text(
        self,
        value: str,
    ) -> str:
        return " ".join(
            value.replace("\n", " ").split()
        )
