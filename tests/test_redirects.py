"""Redirect policy: same-origin redirects are followed, any other origin is never contacted.

The probe from the 2026-10-17 status check is reproduced with an in-memory
network: the target site answers /about with a 302 to a second host whose
robots.txt disallows everything. Origin means scheme, host and port.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlsplit

import pytest
import requests

from company_briefer.briefer import build_brief
from company_briefer.config import Config
from company_briefer.fetcher import Fetcher
from tests.conftest import HostHandler, ScriptedHosts

Install = Callable[[dict[str, HostHandler]], ScriptedHosts]

HOME = "<html><head><title>A home</title></head><body><h1>Home</h1></body></html>"
PRICING = "<html><head><title>Pricing</title></head><body><h1>Plans</h1></body></html>"
OTHER = "<html><head><title>B other site</title></head><body><h1>Other origin</h1></body></html>"


def site_a(about: Callable[[str], tuple[int, dict[str, str], str]]) -> HostHandler:
    """Target site: /about is whatever the test needs, everything else is plain."""

    def handler(path: str) -> tuple[int, dict[str, str], str]:
        if path == "/robots.txt":
            return 404, {}, "no robots"
        if path == "/":
            return 200, {}, HOME
        if path == "/pricing":
            return 200, {}, PRICING
        if path in ("/about", "/about/"):
            return about(path)
        return 404, {}, "not found"

    return handler


def site_b(path: str) -> tuple[int, dict[str, str], str]:
    """The other host: disallows everything in robots.txt, serves a page elsewhere."""
    if path == "/robots.txt":
        return 200, {}, "User-agent: *\nDisallow: /\n"
    return 200, {}, OTHER


def redirect_to(target: str, status: int = 302) -> Callable[[str], tuple[int, dict[str, str], str]]:
    return lambda path: (status, {"Location": target}, "")


def test_cross_origin_redirect_is_not_followed(scripted_hosts: Install, config: Config) -> None:
    net = scripted_hosts(
        {
            "a.example": site_a(redirect_to("https://b.example/other-page")),
            "b.example": site_b,
        }
    )

    result = build_brief("a.example", config, use_cache=False)

    # The other host is never contacted: not for the page, not for its robots.txt.
    assert net.hosts_contacted() == {"a.example"}
    assert "https://b.example/robots.txt" not in net.log
    assert "https://b.example/other-page" not in net.log
    # The crawl stops for that path only; the other paths are still fetched.
    assert {p.url for p in result.evidence.pages} == {
        "https://a.example/",
        "https://a.example/pricing",
    }
    assert "Other origin" not in result.model_dump_json()
    # The redirect target is surfaced in the evidence bundle.
    assert any(
        "https://a.example/about" in note
        and "redirects to another origin" in note
        and "https://b.example/other-page" in note
        and "not followed" in note
        for note in result.evidence.robots_notes
    )


def test_same_origin_redirect_is_still_followed(scripted_hosts: Install, config: Config) -> None:
    def about(path: str) -> tuple[int, dict[str, str], str]:
        if path == "/about":
            return 301, {"Location": "/about/"}, ""  # relative Location, same origin
        return 200, {}, "<html><head><title>About us</title></head><body></body></html>"

    net = scripted_hosts({"a.example": site_a(about)})

    result = build_brief("a.example", config, use_cache=False)

    titles = {p.url: p.title for p in result.evidence.pages}
    assert titles["https://a.example/about"] == "About us"
    assert "https://a.example/about/" in net.log
    assert not any("redirects to another origin" in n for n in result.evidence.robots_notes)


def test_scheme_change_counts_as_another_origin(scripted_hosts: Install, config: Config) -> None:
    net = scripted_hosts({"a.example": site_a(redirect_to("https://a.example/about", status=301))})

    result = build_brief("http://a.example", config, use_cache=False)

    assert not any(u.startswith("https://") for u in net.log)  # the https URL was never requested
    assert any("redirects to another origin" in n for n in result.evidence.robots_notes)


def test_redirect_target_is_reported_without_query_or_contact_data(
    scripted_hosts: Install, config: Config
) -> None:
    target = "https://b.example/landing?email=jo@acme.example&token=abc123"
    scripted_hosts({"a.example": site_a(redirect_to(target)), "b.example": site_b})

    result = build_brief("a.example", config, use_cache=False)

    notes = " ".join(result.evidence.robots_notes)
    assert "https://b.example/landing" in notes
    assert "jo@acme.example" not in notes
    assert "token=abc123" not in notes
    assert "?" not in notes


def test_unparseable_redirect_target_is_never_followed(
    scripted_hosts: Install, config: Config
) -> None:
    net = scripted_hosts({"a.example": site_a(redirect_to("https://b.example:99999/x"))})

    result = build_brief("a.example", config, use_cache=False)

    assert net.hosts_contacted() == {"a.example"}
    assert any("(unparseable URL)" in n for n in result.evidence.robots_notes)


def test_redirect_without_location_is_an_ordinary_status(
    scripted_hosts: Install, config: Config
) -> None:
    scripted_hosts({"a.example": site_a(lambda path: (302, {}, ""))})

    result = build_brief("a.example", config, use_cache=False)

    assert any(
        "skipped https://a.example/about: HTTP 302" in n for n in result.evidence.robots_notes
    )


def test_same_origin_redirect_loop_gives_up(scripted_hosts: Install, config: Config) -> None:
    scripted_hosts({"a.example": site_a(redirect_to("/about"))})

    with pytest.raises(requests.TooManyRedirects):
        Fetcher(config, use_cache=False).fetch_page("https://a.example/about")

    result = build_brief("a.example", config, use_cache=False)
    assert any(
        "fetch failed for https://a.example/about: TooManyRedirects" in n
        for n in result.evidence.robots_notes
    )


def test_cached_pages_are_unaffected_by_redirect_handling(
    scripted_hosts: Install, config: Config
) -> None:
    net = scripted_hosts({"a.example": site_a(redirect_to("https://b.example/x"))})
    fetcher = Fetcher(config, use_cache=True)

    first = fetcher.fetch_page("https://a.example/")
    second = fetcher.fetch_page("https://a.example/")

    assert first.status == 200 and not first.from_cache
    assert second.from_cache
    assert urlsplit(net.log[0]).path == "/"
    assert len(net.log) == 1
