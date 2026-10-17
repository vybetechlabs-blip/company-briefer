"""HTTP layer: robots.txt retrieval, polite page fetching, and on-disk caching.

All network IO lives behind this module so tests can mock a single seam
(`requests.Session.get`). Politeness is enforced here: descriptive User-Agent,
per-request timeout, a rate-limit delay between requests, and one bounded
retry with backoff. Redirects are followed one hop at a time and only within
the origin that was asked for (scheme, host and port); a redirect to any other
origin is never requested.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

from company_briefer.config import Config
from company_briefer.scrub import scrub_text

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_DEFAULT_PORTS = {"http": 80, "https": 443}


class RobotsUnavailableError(Exception):
    """robots.txt could not be read, so nothing may be fetched from the site."""


@dataclass(frozen=True)
class FetchedPage:
    url: str
    status: int
    html: str
    fetched_at: datetime
    from_cache: bool = False
    # Set when the server redirected to another origin; that target was not requested.
    redirect_to: str | None = None


def _origin(url: str) -> tuple[str, str, int | None] | None:
    """Scheme, host and port of *url*, or None when it cannot be parsed."""
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        return scheme, (parts.hostname or "").lower(), parts.port or _DEFAULT_PORTS.get(scheme)
    except ValueError:
        return None


def _same_origin(a: str, b: str) -> bool:
    origin = _origin(a)
    return origin is not None and origin == _origin(b)


def describe_target(url: str) -> str:
    """A redirect target safe to print: no credentials, query, fragment or contact data."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return "(unparseable URL)"
    return scrub_text(f"{parts.scheme}://{host}{port}{parts.path}")


class Fetcher:
    """Polite HTTP client for a single briefing run."""

    def __init__(self, config: Config, *, use_cache: bool = True) -> None:
        self.config = config
        self.use_cache = use_cache
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.user_agent
        self._last_request_at = 0.0

    def fetch_robots(self, origin: str) -> str | None:
        """Fetch robots.txt for *origin*; None means the site publishes none (HTTP 4xx).

        Fail-closed: if robots.txt cannot be read (connection error, timeout, a 5xx
        or other unusable answer, or a redirect to another origin) the crawl is
        refused with `RobotsUnavailableError` instead of assuming permission.
        """
        url = f"{origin}/robots.txt"
        try:
            resp, blocked = self._follow(url, self._get)
        except requests.Timeout as exc:
            raise RobotsUnavailableError(f"{url} timed out") from exc
        except requests.RequestException as exc:
            raise RobotsUnavailableError(f"{url} failed ({exc.__class__.__name__})") from exc
        if blocked is not None:
            raise RobotsUnavailableError(
                f"{url} redirects to another origin ({describe_target(blocked)})"
            )
        if resp.status_code == 200:
            return resp.text
        if 400 <= resp.status_code < 500:
            return None
        raise RobotsUnavailableError(f"{url} returned HTTP {resp.status_code}")

    def fetch_page(self, url: str) -> FetchedPage:
        """Fetch one page, serving from the on-disk cache when possible.

        A redirect within the origin is followed. A redirect to another origin is
        not requested: the result carries its status and `redirect_to` instead.
        """
        if self.use_cache:
            cached = self._cache_read(url)
            if cached is not None:
                return cached
        resp, blocked = self._follow(url, self._get_with_retry)
        if blocked is not None:
            return FetchedPage(
                url=url,
                status=resp.status_code,
                html="",
                fetched_at=datetime.now(UTC),
                redirect_to=describe_target(blocked),
            )
        # requests defaults text/* without a charset header to ISO-8859-1, which
        # garbles UTF-8 pages; fall back to detection when no charset is declared.
        if "charset" not in resp.headers.get("Content-Type", "").lower():
            resp.encoding = resp.apparent_encoding
        page = FetchedPage(
            url=url, status=resp.status_code, html=resp.text, fetched_at=datetime.now(UTC)
        )
        if self.use_cache and page.status == 200:
            self._cache_write(page)
        return page

    def _get(self, url: str) -> requests.Response:
        """One request, never following a redirect: `_follow` decides where to go."""
        self._respect_rate_limit()
        return self.session.get(url, timeout=self.config.timeout_seconds, allow_redirects=False)

    def _follow(
        self, url: str, get: Callable[[str], requests.Response]
    ) -> tuple[requests.Response, str | None]:
        """Follow redirects within the origin of *url*; stop at the first one that leaves it.

        Returns the final response and, when a redirect led to another origin, that
        target (never requested). Exceeding the session's redirect limit raises
        `requests.TooManyRedirects`, as `requests` itself would.
        """
        current = url
        for _ in range(self.session.max_redirects + 1):
            resp = get(current)
            if resp.status_code not in REDIRECT_STATUSES:
                return resp, None
            location = resp.headers.get("Location")
            if not location:
                return resp, None
            target = urljoin(current, location)
            if not _same_origin(url, target):
                return resp, target
            current = target
        raise requests.TooManyRedirects(f"exceeded {self.session.max_redirects} redirects")

    def _get_with_retry(self, url: str) -> requests.Response:
        """One bounded retry with backoff on connection errors or 5xx responses."""
        try:
            resp = self._get(url)
        except requests.RequestException:
            time.sleep(self._backoff_seconds())
            return self._get(url)
        if resp.status_code >= 500:
            time.sleep(self._backoff_seconds())
            return self._get(url)
        return resp

    def _backoff_seconds(self) -> float:
        return self.config.rate_limit_seconds * 2

    def _respect_rate_limit(self) -> None:
        if self.config.rate_limit_seconds <= 0 or self._last_request_at == 0.0:
            self._last_request_at = time.monotonic()
            return
        wait = self.config.rate_limit_seconds - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
        return self.config.cache_dir / f"{digest}.json"

    def _cache_read(self, url: str) -> FetchedPage | None:
        path = self._cache_path(url)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return FetchedPage(
                url=str(raw["url"]),
                status=int(raw["status"]),
                html=str(raw["html"]),
                fetched_at=datetime.fromisoformat(raw["fetched_at"]),
                from_cache=True,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def _cache_write(self, page: FetchedPage) -> None:
        path = self._cache_path(page.url)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "url": page.url,
            "status": page.status,
            "html": page.html,
            "fetched_at": page.fetched_at.isoformat(),
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
