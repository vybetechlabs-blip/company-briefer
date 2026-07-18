"""HTTP layer: robots.txt retrieval, polite page fetching, and on-disk caching.

All network IO lives behind this module so tests can mock a single seam
(`requests.Session.get`). Politeness is enforced here: descriptive User-Agent,
per-request timeout, a rate-limit delay between requests, and one bounded
retry with backoff.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import requests

from company_briefer.config import Config


@dataclass(frozen=True)
class FetchedPage:
    url: str
    status: int
    html: str
    fetched_at: datetime
    from_cache: bool = False


class Fetcher:
    """Polite HTTP client for a single briefing run."""

    def __init__(self, config: Config, *, use_cache: bool = True) -> None:
        self.config = config
        self.use_cache = use_cache
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.user_agent
        self._last_request_at = 0.0

    def fetch_robots(self, origin: str) -> str | None:
        """Fetch robots.txt for *origin*. None means unreachable or not present."""
        try:
            resp = self._get(f"{origin}/robots.txt")
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        return resp.text

    def fetch_page(self, url: str) -> FetchedPage:
        """Fetch one page, serving from the on-disk cache when possible."""
        if self.use_cache:
            cached = self._cache_read(url)
            if cached is not None:
                return cached
        resp = self._get_with_retry(url)
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
        self._respect_rate_limit()
        return self.session.get(url, timeout=self.config.timeout_seconds)

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
