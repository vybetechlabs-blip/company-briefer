"""The page cache holds scrubbed pages only: no email or phone number reaches the disk.

Regression for the cache probe: a page carrying a plain email, the same email
written as an HTML entity, and a phone number is fetched and cached; every cache
file is then searched for each of them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from company_briefer.briefer import build_brief
from company_briefer.cache import PageCache
from company_briefer.config import Config
from company_briefer.models import PageContent
from tests.conftest import FakeResponse
from tests.test_redirects import Install

CONTACT_PAGE = (
    "<html><head><title>Acme</title></head><body><h1>Acme Signals</h1>"
    "<p>Write to jo@acme-signals.example or to jo&#64;acme-signals.example, "
    "or call +1 (555) 123-4567.</p>"
    '<p><a href="mailto:sales@acme-signals.example">Email</a> '
    '<a href="tel:+15551234567">Call</a></p></body></html>'
)

# Everything the probe page holds that must never be written to disk.
SECRETS = [
    "jo@acme-signals.example",
    "jo&#64;acme-signals.example",
    "sales@acme-signals.example",
    "@acme-signals",
    "&#64;",
    "(555)",
    "123-4567",
    "15551234567",
]


def _site(path: str) -> tuple[int, dict[str, str], str]:
    if path == "/":
        return 200, {}, CONTACT_PAGE
    return 404, {}, "not found"


def _cache_text(config: Config) -> str:
    files = sorted(config.cache_dir.glob("*"))
    assert files, "the probe wrote no cache file, so the search below would prove nothing"
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


def test_no_cache_file_holds_the_probe_email_or_phone(
    scripted_hosts: Install, config: Config
) -> None:
    scripted_hosts({"a.example": _site})

    result = build_brief("a.example", config)

    cached = _cache_text(config)
    for secret in SECRETS:
        assert secret not in cached, f"{secret!r} reached the cache"
    assert "[redacted]" in cached  # the page was cached, in scrubbed form
    # The same holds for what the run prints and hands to a model.
    dumped = result.model_dump_json()
    for secret in SECRETS:
        assert secret not in dumped, f"{secret!r} reached the output"


def test_cache_file_is_exactly_the_scrubbed_evidence_page(
    scripted_hosts: Install, config: Config
) -> None:
    scripted_hosts({"a.example": _site})

    result = build_brief("a.example", config)

    files = list(config.cache_dir.glob("*.json"))
    assert len(files) == 1
    cached = PageContent.model_validate_json(files[0].read_text(encoding="utf-8"))
    assert cached == result.evidence.pages[0]


def test_second_run_is_served_from_the_cache(scripted_hosts: Install, config: Config) -> None:
    net = scripted_hosts({"a.example": _site})

    first = build_brief("a.example", config)
    requests_after_first = len(net.log)
    second = build_brief("a.example", config)

    second_run = net.log[requests_after_first:]
    assert "https://a.example/" not in second_run  # the cached page is not requested again
    assert "https://a.example/robots.txt" in second_run  # robots.txt is never cached
    assert second.evidence.pages == first.evidence.pages


def test_no_cache_writes_nothing_to_disk(fake_site: list[dict[str, Any]], config: Config) -> None:
    build_brief("example.com", config, use_cache=False)
    assert not config.cache_dir.exists()


def test_non_200_pages_are_not_cached(fake_site: list[dict[str, Any]], config: Config) -> None:
    build_brief("example.com", config)
    cached_urls = {
        PageContent.model_validate_json(f.read_text(encoding="utf-8")).url
        for f in config.cache_dir.glob("*.json")
    }
    assert cached_urls == {
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/pricing",
    }  # the 404 paths were refetched each run, never cached


def test_corrupt_cache_entry_falls_back_to_http(
    fake_site: list[dict[str, Any]], config: Config
) -> None:
    build_brief("example.com", config)
    for cache_file in config.cache_dir.glob("*.json"):
        cache_file.write_text("{not json", encoding="utf-8")
    fake_site.clear()

    result = build_brief("example.com", config)

    assert {p.url for p in result.evidence.pages} >= {"https://example.com/"}
    assert any(c["url"].endswith("/pricing") for c in fake_site)  # fetched again


def test_a_changed_text_limit_does_not_serve_a_stale_page(
    fake_site: list[dict[str, Any]], config: Config
) -> None:
    build_brief("example.com", config)
    fake_site.clear()

    shorter = config.model_copy(update={"max_page_chars": 600})
    build_brief("example.com", shorter)

    assert any(c["url"].endswith("/pricing") for c in fake_site)  # re-fetched, not reused


def test_cache_entry_for_another_url_reads_as_a_miss(config: Config, tmp_path: Path) -> None:
    cache = PageCache(tmp_path / "c", config.max_page_chars)
    other = PageContent(
        url="https://example.com/other", status=200, fetched_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    cache.write(other)
    # Move that entry to where https://example.com/ would look for its own.
    wanted = cache._path("https://example.com/")
    cache._path(other.url).replace(wanted)
    assert cache.read("https://example.com/") is None


def test_a_run_that_fetches_nothing_caches_nothing(monkeypatch: Any, config: Config) -> None:
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: FakeResponse(404, "x"))
    result = build_brief("example.com", config)
    assert result.evidence.pages == []
    assert not config.cache_dir.exists()
