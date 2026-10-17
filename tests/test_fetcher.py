"""Fetcher: UA header, timeout, retry, robots retrieval, cache. Network fully mocked."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from company_briefer.config import Config
from company_briefer.fetcher import Fetcher
from tests.conftest import FakeResponse


def test_descriptive_user_agent_is_sent(fake_site: list[dict[str, Any]], config: Config) -> None:
    Fetcher(config).fetch_page("https://example.com/")
    assert fake_site, "no request captured"
    assert fake_site[0]["headers"]["User-Agent"] == config.user_agent
    assert "company-briefer" in config.user_agent
    assert "github.com" in config.user_agent  # UA points readers at the repo


def test_timeout_is_applied(fake_site: list[dict[str, Any]], config: Config) -> None:
    Fetcher(config).fetch_page("https://example.com/")
    assert fake_site[0]["timeout"] == config.timeout_seconds


def test_fetch_robots_returns_text(fake_site: list[dict[str, Any]], config: Config) -> None:
    robots = Fetcher(config).fetch_robots("https://example.com")
    assert robots is not None
    assert "Disallow: /platform" in robots


def test_fetch_robots_none_when_missing(monkeypatch: pytest.MonkeyPatch, config: Config) -> None:
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: FakeResponse(404, "nope"))
    assert Fetcher(config).fetch_robots("https://example.com") is None


def test_one_retry_on_server_error(monkeypatch: pytest.MonkeyPatch, config: Config) -> None:
    statuses = iter([500, 200])
    calls: list[str] = []

    def flaky_get(self: requests.Session, url: str, **kw: Any) -> FakeResponse:
        calls.append(url)
        return FakeResponse(next(statuses), "<html><body>ok</body></html>")

    monkeypatch.setattr(requests.Session, "get", flaky_get)
    page = Fetcher(config).fetch_page("https://example.com/")
    assert page.status == 200
    assert len(calls) == 2


def test_retry_gives_up_after_second_failure(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    def always_broken(self: requests.Session, url: str, **kw: Any) -> FakeResponse:
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(requests.Session, "get", always_broken)
    with pytest.raises(requests.ConnectionError):
        Fetcher(config).fetch_page("https://example.com/")


def test_rate_limit_delay_between_requests(
    fake_site: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("company_briefer.fetcher.time.sleep", sleeps.append)
    polite = config.model_copy(update={"rate_limit_seconds": 1.0})
    fetcher = Fetcher(polite)
    fetcher.fetch_page("https://example.com/")
    fetcher.fetch_page("https://example.com/about")
    assert sleeps, "no rate-limit delay applied between consecutive requests"
    assert all(0 < s <= 1.0 for s in sleeps)


def test_utf8_page_without_charset_header_decodes_correctly(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """Servers that omit charset default to ISO-8859-1 in requests; we must detect UTF-8."""
    html = "<html><head><title>Acme — Signals</title></head><body>café</body></html>"
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: FakeResponse(200, html))
    page = Fetcher(config).fetch_page("https://example.com/")
    assert "Acme — Signals" in page.html
    assert "café" in page.html
