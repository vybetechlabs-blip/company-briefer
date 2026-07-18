"""Fetcher: UA header, timeout, retry, robots retrieval, cache. Network fully mocked."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from company_briefer.config import Config
from company_briefer.fetcher import Fetcher
from tests.conftest import FakeResponse


def test_descriptive_user_agent_is_sent(fake_site: list[dict[str, Any]], config: Config) -> None:
    Fetcher(config, use_cache=False).fetch_page("https://example.com/")
    assert fake_site, "no request captured"
    assert fake_site[0]["headers"]["User-Agent"] == config.user_agent
    assert "company-briefer" in config.user_agent
    assert "github.com" in config.user_agent  # UA points readers at the repo


def test_timeout_is_applied(fake_site: list[dict[str, Any]], config: Config) -> None:
    Fetcher(config, use_cache=False).fetch_page("https://example.com/")
    assert fake_site[0]["timeout"] == config.timeout_seconds


def test_fetch_robots_returns_text(fake_site: list[dict[str, Any]], config: Config) -> None:
    robots = Fetcher(config, use_cache=False).fetch_robots("https://example.com")
    assert robots is not None
    assert "Disallow: /platform" in robots


def test_fetch_robots_none_when_missing(monkeypatch: pytest.MonkeyPatch, config: Config) -> None:
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: FakeResponse(404, "nope"))
    assert Fetcher(config, use_cache=False).fetch_robots("https://example.com") is None


def test_one_retry_on_server_error(monkeypatch: pytest.MonkeyPatch, config: Config) -> None:
    statuses = iter([500, 200])
    calls: list[str] = []

    def flaky_get(self: requests.Session, url: str, **kw: Any) -> FakeResponse:
        calls.append(url)
        return FakeResponse(next(statuses), "<html><body>ok</body></html>")

    monkeypatch.setattr(requests.Session, "get", flaky_get)
    page = Fetcher(config, use_cache=False).fetch_page("https://example.com/")
    assert page.status == 200
    assert len(calls) == 2


def test_retry_gives_up_after_second_failure(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    def always_broken(self: requests.Session, url: str, **kw: Any) -> FakeResponse:
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(requests.Session, "get", always_broken)
    with pytest.raises(requests.ConnectionError):
        Fetcher(config, use_cache=False).fetch_page("https://example.com/")


def test_cache_serves_second_fetch_without_http(
    fake_site: list[dict[str, Any]], config: Config
) -> None:
    fetcher = Fetcher(config, use_cache=True)
    first = fetcher.fetch_page("https://example.com/")
    second = fetcher.fetch_page("https://example.com/")
    assert not first.from_cache
    assert second.from_cache
    assert second.html == first.html
    assert len(fake_site) == 1  # exactly one HTTP request for two fetches


def test_no_cache_bypasses_disk(fake_site: list[dict[str, Any]], config: Config) -> None:
    fetcher = Fetcher(config, use_cache=False)
    fetcher.fetch_page("https://example.com/")
    fetcher.fetch_page("https://example.com/")
    assert len(fake_site) == 2
    assert not config.cache_dir.exists()


def test_rate_limit_delay_between_requests(
    fake_site: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("company_briefer.fetcher.time.sleep", sleeps.append)
    polite = config.model_copy(update={"rate_limit_seconds": 1.0})
    fetcher = Fetcher(polite, use_cache=False)
    fetcher.fetch_page("https://example.com/")
    fetcher.fetch_page("https://example.com/about")
    assert sleeps, "no rate-limit delay applied between consecutive requests"
    assert all(0 < s <= 1.0 for s in sleeps)


def test_corrupt_cache_entry_falls_back_to_http(
    fake_site: list[dict[str, Any]], config: Config
) -> None:
    fetcher = Fetcher(config, use_cache=True)
    fetcher.fetch_page("https://example.com/")
    cache_files = list(config.cache_dir.glob("*.json"))
    assert len(cache_files) == 1
    cache_files[0].write_text("{not json", encoding="utf-8")
    page = fetcher.fetch_page("https://example.com/")
    assert not page.from_cache
    assert len(fake_site) == 2


def test_utf8_page_without_charset_header_decodes_correctly(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """Servers that omit charset default to ISO-8859-1 in requests; we must detect UTF-8."""
    html = "<html><head><title>Acme — Signals</title></head><body>café</body></html>"
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: FakeResponse(200, html))
    page = Fetcher(config, use_cache=False).fetch_page("https://example.com/")
    assert "Acme — Signals" in page.html
    assert "café" in page.html


def test_non_200_pages_are_not_cached(fake_site: list[dict[str, Any]], config: Config) -> None:
    fetcher = Fetcher(config, use_cache=True)
    fetcher.fetch_page("https://example.com/missing")
    fetcher.fetch_page("https://example.com/missing")
    assert len(fake_site) == 2  # 404 was refetched, never cached
