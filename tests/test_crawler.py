"""Crawler: origin normalization, allowlist plan, same-origin, robots, page cap."""

from __future__ import annotations

import pytest

from company_briefer.crawler import RobotsPolicy, normalize_origin, plan_fetch

UA = "company-briefer/0.1 (+https://github.com/vybetechlabs-blip/company-briefer)"
ROBOTS = "User-agent: *\nDisallow: /platform\nDisallow: /solutions\n"


class TestNormalizeOrigin:
    def test_bare_domain_gets_https(self) -> None:
        assert normalize_origin("example.com") == "https://example.com"

    def test_url_with_path_is_reduced_to_origin(self) -> None:
        assert normalize_origin("http://example.com/pricing?x=1") == "http://example.com"

    def test_port_is_preserved(self) -> None:
        assert normalize_origin("http://127.0.0.1:8043/foo") == "http://127.0.0.1:8043"

    @pytest.mark.parametrize("bad", ["", "   ", "not a domain!!", "ftp://example.com"])
    def test_invalid_input_raises(self, bad: str) -> None:
        with pytest.raises(ValueError):
            normalize_origin(bad)


class TestRobotsPolicy:
    def test_missing_robots_allows_everything(self) -> None:
        policy = RobotsPolicy(None, UA)
        assert policy.can_fetch("https://example.com/platform")

    def test_disallowed_path_is_blocked(self) -> None:
        policy = RobotsPolicy(ROBOTS, UA)
        assert not policy.can_fetch("https://example.com/platform")
        assert policy.can_fetch("https://example.com/pricing")


class TestPlanFetch:
    def test_only_allowlisted_same_origin_urls(self) -> None:
        policy = RobotsPolicy(None, UA)
        urls, _ = plan_fetch("https://example.com", ("/", "/about"), policy, max_pages=8)
        assert urls == ["https://example.com/", "https://example.com/about"]
        assert all(u.startswith("https://example.com/") for u in urls)

    def test_robots_disallow_is_skipped_and_noted(self) -> None:
        policy = RobotsPolicy(ROBOTS, UA)
        urls, notes = plan_fetch(
            "https://example.com", ("/", "/platform", "/pricing"), policy, max_pages=8
        )
        assert "https://example.com/platform" not in urls
        assert "https://example.com/pricing" in urls
        assert any("robots.txt" in n and "/platform" in n for n in notes)

    def test_page_cap_is_enforced(self) -> None:
        policy = RobotsPolicy(None, UA)
        allowlist = tuple(f"/p{i}" for i in range(20))
        urls, notes = plan_fetch("https://example.com", allowlist, policy, max_pages=3)
        assert len(urls) == 3
        assert any("page cap" in n for n in notes)
