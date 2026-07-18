"""Extractor: titles, meta, headings, nav/CTA labels, main text, boilerplate removal."""

from __future__ import annotations

from datetime import UTC, datetime

from company_briefer.extractor import extract_page
from tests.conftest import load_fixture

NOW = datetime(2026, 7, 18, tzinfo=UTC)


def test_title_and_meta_description() -> None:
    page = extract_page("https://example.com/", 200, load_fixture("home.html"), NOW)
    assert page.title == "Acme Signals — Revenue intelligence for B2B teams"
    assert page.meta_description is not None
    assert "CRM noise" in page.meta_description


def test_headings_h1_to_h3() -> None:
    page = extract_page("https://example.com/", 200, load_fixture("home.html"), NOW)
    assert "Pipeline you can trust" in page.headings
    assert "Built for B2B revenue teams" in page.headings
    assert "Forecasting without the folklore" in page.headings


def test_nav_and_cta_labels() -> None:
    page = extract_page("https://example.com/", 200, load_fixture("home.html"), NOW)
    assert "Pricing" in page.nav_labels
    assert "Start free trial" in page.nav_labels  # CTA by class hint
    page_about = extract_page("https://example.com/about", 200, load_fixture("about.html"), NOW)
    assert "Book a demo" in page_about.nav_labels  # <button class="cta">


def test_scripts_styles_and_chrome_excluded() -> None:
    page = extract_page("https://example.com/", 200, load_fixture("home.html"), NOW)
    assert "should never appear" not in page.main_text
    assert "rebeccapurple" not in page.main_text
    assert "© Acme Signals" not in page.main_text  # footer dropped from body text


def test_main_text_contains_marketing_copy() -> None:
    page = extract_page("https://example.com/", 200, load_fixture("home.html"), NOW)
    assert "surfaces the deals" in page.main_text
    assert "400 revenue teams" in page.main_text.replace("  ", " ")


def test_main_text_is_truncated_to_cap() -> None:
    page = extract_page(
        "https://example.com/", 200, load_fixture("home.html"), NOW, max_text_chars=500
    )
    assert len(page.main_text) <= 502  # cap + ellipsis marker


def test_pages_without_optional_fields() -> None:
    page = extract_page("https://example.com/x", 200, "<html><body>hi</body></html>", NOW)
    assert page.title is None
    assert page.meta_description is None
    assert page.headings == []
    assert page.main_text == "hi"
