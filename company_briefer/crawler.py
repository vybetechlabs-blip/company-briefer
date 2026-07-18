"""Decide which URLs to fetch: allowlisted paths, same origin, robots-permitted, capped.

Pure logic, no IO. The fetcher supplies robots.txt text; this module parses it
and produces the bounded fetch plan plus notes about anything skipped. URLs are
only ever constructed from the base origin plus allowlisted paths — discovered
links are never followed, so the crawl cannot leave the target domain.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

_NETLOC_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::\d{1,5})?$")


def normalize_origin(domain_or_url: str) -> str:
    """Normalize user input ('example.com', 'http://example.com/x') to a base origin."""
    raw = domain_or_url.strip()
    if not raw:
        raise ValueError("empty domain")
    if "://" not in raw:
        raw = f"https://{raw}"
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not _NETLOC_RE.match(parsed.netloc):
        raise ValueError(f"cannot derive a valid origin from {domain_or_url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


class RobotsPolicy:
    """Wrapper over parsed robots.txt rules. Missing robots.txt means allow-all."""

    def __init__(self, robots_txt: str | None, user_agent: str) -> None:
        self._user_agent = user_agent
        self._parser: RobotFileParser | None = None
        if robots_txt is not None:
            parser = RobotFileParser()
            parser.parse(robots_txt.splitlines())
            self._parser = parser

    def can_fetch(self, url: str) -> bool:
        if self._parser is None:
            return True
        return self._parser.can_fetch(self._user_agent, url)


def plan_fetch(
    origin: str,
    allowlist: Sequence[str],
    policy: RobotsPolicy,
    max_pages: int,
) -> tuple[list[str], list[str]]:
    """Return ``(urls_to_fetch, notes)``.

    Only allowlisted paths on *origin*, only where robots.txt permits, and
    never more than *max_pages* URLs.
    """
    urls: list[str] = []
    notes: list[str] = []
    base = origin.rstrip("/")
    for path in allowlist:
        if len(urls) >= max_pages:
            notes.append(f"page cap ({max_pages}) reached; skipped remaining allowlisted paths")
            break
        url = f"{base}{path}" if path != "/" else f"{base}/"
        if policy.can_fetch(url):
            urls.append(url)
        else:
            notes.append(f"skipped {path}: disallowed by robots.txt")
    return urls, notes
