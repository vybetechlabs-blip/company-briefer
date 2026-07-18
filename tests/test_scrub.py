"""Scrub: seeded contact data is removed; ordinary numbers survive."""

from __future__ import annotations

from datetime import UTC, datetime

from company_briefer.extractor import extract_page
from company_briefer.scrub import REDACTED, scrub_page, scrub_text
from tests.conftest import load_fixture

NOW = datetime(2026, 7, 18, tzinfo=UTC)


class TestScrubText:
    def test_email_is_removed(self) -> None:
        out = scrub_text("Contact sales@acme-signals.example for details")
        assert "sales@" not in out
        assert REDACTED in out

    def test_phone_is_removed(self) -> None:
        out = scrub_text("call +1 (555) 123-4567 today")
        assert "555" not in out
        assert REDACTED in out

    def test_plain_digit_run_phone(self) -> None:
        assert "5551234567" not in scrub_text("ring 5551234567 now")

    def test_prices_and_years_survive(self) -> None:
        text = "$49 per seat since 2019, saving teams 30% on 3 tools"
        assert scrub_text(text) == text

    def test_versions_survive(self) -> None:
        text = "works with Python 3.11 and HTTP/2"
        assert scrub_text(text) == text


class TestScrubPage:
    def test_seeded_fixture_page_comes_out_clean(self) -> None:
        """The pricing fixture is deliberately seeded with an email + phone."""
        raw = load_fixture("pricing.html")
        assert "sales@acme-signals.example" in raw
        assert "123-4567" in raw

        page = extract_page("https://example.com/pricing", 200, raw, NOW)
        scrubbed = scrub_page(page)

        dumped = scrubbed.model_dump_json()
        assert "sales@acme-signals.example" not in dumped
        assert "123-4567" not in dumped
        assert "(555)" not in dumped
        # the surrounding marketing copy is intact
        assert "seat-based pricing" in dumped
        assert "$49" in dumped

    def test_all_fields_are_scrubbed(self) -> None:
        page = extract_page(
            "https://example.com/x",
            200,
            "<html><head><title>mail me a@b.co</title>"
            '<meta name="description" content="call 555-123-4567 x"></head>'
            "<body><nav><a>ring 555-123-4567</a></nav><main><h1>a@b.co</h1>"
            "<p>a@b.co and 555-123-4567</p></main></body></html>",
            NOW,
        )
        dumped = scrub_page(page).model_dump_json()
        assert "a@b.co" not in dumped
        assert "555-123-4567" not in dumped
