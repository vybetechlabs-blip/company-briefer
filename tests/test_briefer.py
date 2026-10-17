"""End-to-end pipeline over the fixture site — zero network, zero API calls."""

from __future__ import annotations

from typing import Any

from company_briefer.briefer import build_brief
from company_briefer.config import Config


def test_full_pipeline_over_fixture_site(fake_site: list[dict[str, Any]], config: Config) -> None:
    result = build_brief("example.com", config)

    assert result.domain == "https://example.com"
    assert result.synthesis_status == "skipped_not_requested"
    assert result.brief is None

    fetched_urls = {p.url for p in result.evidence.pages}
    assert fetched_urls == {
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/pricing",
    }

    # robots-disallowed paths were never requested at all
    requested = [c["url"] for c in fake_site]
    assert not any("/platform" in u for u in requested)
    assert not any("/solutions" in u for u in requested)
    assert any("robots.txt" in n and "/platform" in n for n in result.evidence.robots_notes)

    # 404s on allowlisted paths are noted, not fatal
    assert any("HTTP 404" in n for n in result.evidence.robots_notes)


def test_no_contact_data_anywhere_in_result(
    fake_site: list[dict[str, Any]], config: Config
) -> None:
    """The pricing fixture seeds an email + phone; nothing may survive to output."""
    result = build_brief("example.com", config)
    dumped = result.model_dump_json()
    assert "sales@acme-signals.example" not in dumped
    assert "@acme-signals" not in dumped
    assert "123-4567" not in dumped
    assert "(555)" not in dumped


def test_llm_requested_without_key_degrades(
    fake_site: list[dict[str, Any]], config: Config
) -> None:
    result = build_brief("example.com", config, llm=True)
    assert result.synthesis_status == "skipped_no_api_key"
    assert result.brief is None
    assert result.evidence.pages  # evidence still emitted


def test_absent_robots_is_noted_and_failed_pages_do_not_stop_the_pipeline(
    monkeypatch: Any, config: Config
) -> None:
    import requests

    from tests.conftest import FakeResponse

    def no_robots_and_pages_down(self: Any, url: str, **kw: Any) -> Any:
        if url.endswith("/robots.txt"):
            return FakeResponse(404, "not found")
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(requests.Session, "get", no_robots_and_pages_down)
    result = build_brief("example.com", config)
    assert any("no robots.txt published" in n for n in result.evidence.robots_notes)
    assert result.evidence.pages == []
    assert any("fetch failed" in n for n in result.evidence.robots_notes)
