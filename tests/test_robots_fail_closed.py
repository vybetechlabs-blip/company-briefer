"""robots.txt that cannot be read means no crawl: fail-closed, at every layer.

Three ways it can be unreadable (connection error, timeout, HTTP 5xx), each
checked in the fetcher, the pipeline and the CLI. A site that publishes no
robots.txt (HTTP 4xx) is a different case and still allows the allowlisted paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests
from typer.testing import CliRunner

from company_briefer import cli
from company_briefer.briefer import build_brief
from company_briefer.config import Config
from company_briefer.fetcher import Fetcher, RobotsUnavailableError
from tests.conftest import FakeResponse
from tests.test_redirects import Install, site_a

runner = CliRunner()

# case name -> text the error must contain
CASES = {
    "connection_error": "ConnectionError",
    "timeout": "timed out",
    "server_error": "HTTP 503",
}


def break_robots(monkeypatch: pytest.MonkeyPatch, case: str) -> list[str]:
    """Make every request fail the given way; return the log of URLs requested."""
    calls: list[str] = []

    def get(self: requests.Session, url: str, **kwargs: Any) -> FakeResponse:
        calls.append(url)
        if case == "connection_error":
            raise requests.ConnectionError("refused")
        if case == "timeout":
            raise requests.ReadTimeout("slow")
        return FakeResponse(503, "unavailable")

    monkeypatch.setattr(requests.Session, "get", get)
    return calls


@pytest.mark.parametrize("case", CASES)
def test_fetcher_raises_when_robots_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, config: Config, case: str
) -> None:
    break_robots(monkeypatch, case)
    with pytest.raises(RobotsUnavailableError, match=CASES[case]):
        Fetcher(config).fetch_robots("https://example.com")


@pytest.mark.parametrize("case", CASES)
def test_pipeline_fetches_no_page_when_robots_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch, config: Config, case: str
) -> None:
    calls = break_robots(monkeypatch, case)
    with pytest.raises(RobotsUnavailableError):
        build_brief("example.com", config, use_cache=False)
    assert calls == ["https://example.com/robots.txt"]  # one request, no page, no retry


@pytest.mark.parametrize("case", CASES)
def test_cli_exits_3_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch, config: Config, tmp_path: Path, case: str
) -> None:
    monkeypatch.setattr(cli, "Config", lambda: config)
    calls = break_robots(monkeypatch, case)
    target = tmp_path / "result.json"

    result = runner.invoke(cli.app, ["brief", "example.com", "--json", "--out", str(target)])

    assert result.exit_code == 3
    assert "cannot read robots.txt" in result.output
    assert CASES[case] in result.output
    assert "refusing to fetch any page" in result.output
    assert result.stdout.strip() == ""  # no result on stdout
    assert not target.exists()  # and none on disk
    assert calls == ["https://example.com/robots.txt"]


@pytest.mark.parametrize("status", [403, 404, 410])
def test_missing_robots_is_not_a_refusal(
    monkeypatch: pytest.MonkeyPatch, config: Config, status: int
) -> None:
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: FakeResponse(status, "x"))
    assert Fetcher(config).fetch_robots("https://example.com") is None


def test_unusable_redirect_status_for_robots_is_a_refusal(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    """A 3xx with no Location is neither a robots.txt nor a clean absence."""
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: FakeResponse(302, ""))
    with pytest.raises(RobotsUnavailableError, match="HTTP 302"):
        Fetcher(config).fetch_robots("https://example.com")


def test_robots_redirect_to_another_origin_is_a_refusal(
    scripted_hosts: Install, config: Config
) -> None:
    def home(path: str) -> tuple[int, dict[str, str], str]:
        if path == "/robots.txt":
            return 301, {"Location": "https://www.a.example/robots.txt?x=jo@acme.example"}, ""
        return site_a(lambda p: (200, {}, ""))(path)

    net = scripted_hosts({"a.example": home})

    with pytest.raises(RobotsUnavailableError, match="redirects to another origin") as info:
        build_brief("a.example", config, use_cache=False)

    assert "https://www.a.example/robots.txt" in str(info.value)
    assert "jo@acme.example" not in str(info.value)
    assert net.hosts_contacted() == {"a.example"}  # the other host was never requested
    assert net.log == ["https://a.example/robots.txt"]


def test_robots_redirect_within_the_origin_is_followed(
    scripted_hosts: Install, config: Config
) -> None:
    def host(path: str) -> tuple[int, dict[str, str], str]:
        if path == "/robots.txt":
            return 301, {"Location": "/policies/robots.txt"}, ""
        if path == "/policies/robots.txt":
            return 200, {}, "User-agent: *\nDisallow: /pricing\n"
        return site_a(lambda p: (200, {}, ""))(path)

    scripted_hosts({"a.example": host})

    result = build_brief("a.example", config, use_cache=False)

    assert "https://a.example/pricing" not in {p.url for p in result.evidence.pages}
    assert any("disallowed by robots.txt" in n for n in result.evidence.robots_notes)
