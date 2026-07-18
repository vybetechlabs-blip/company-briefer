"""Shared fixtures: fixture-site HTTP mocking, config, and console/env hygiene.

No test in this suite may touch the network. The `_no_real_network` autouse
fixture makes any unmocked HTTP attempt fail loudly; tests that need HTTP use
the `fake_site` fixture, which serves the synthetic site under
tests/fixtures/site/ through a patched `requests.Session.get`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
import requests

from company_briefer.config import Config

FIXTURE_SITE = Path(__file__).parent / "fixtures" / "site"

ROUTES: dict[str, str] = {
    "/robots.txt": "robots.txt",
    "/": "home.html",
    "/about": "about.html",
    "/pricing": "pricing.html",
}


@pytest.fixture(autouse=True)
def _plain_console_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep console output plain under any environment.

    Rich force-enables ANSI styling when it detects a CI provider (e.g. the
    GITHUB_ACTIONS env var), even for non-tty streams like CliRunner's capture
    buffer — which breaks substring assertions on CLI output. Strip the CI
    markers and set NO_COLOR so test output is identical locally and in CI.
    """
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never see a real API key unless they set a dummy one themselves."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hard guard: any HTTP attempt that reaches the transport layer fails."""

    def _blocked(self: requests.Session, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("network access attempted in tests")

    monkeypatch.setattr(requests.Session, "request", _blocked)


class FakeResponse:
    """Mimics requests.Response decoding: no charset header -> ISO-8859-1 default."""

    def __init__(self, status_code: int, text: str, content_type: str = "text/html") -> None:
        self.status_code = status_code
        self._body = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.encoding: str | None = "utf-8" if "charset" in content_type else "ISO-8859-1"

    @property
    def apparent_encoding(self) -> str:
        return "utf-8"

    @property
    def text(self) -> str:
        return self._body.decode(self.encoding or "utf-8", errors="replace")


@pytest.fixture
def fake_site(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Serve the synthetic fixture site; returns a log of every request made."""
    calls: list[dict[str, Any]] = []

    def fake_get(
        self: requests.Session, url: str, timeout: float | None = None, **kwargs: Any
    ) -> FakeResponse:
        calls.append({"url": url, "timeout": timeout, "headers": dict(self.headers)})
        path = urlparse(url).path or "/"
        filename = ROUTES.get(path)
        if filename is None:
            return FakeResponse(404, "not found")
        return FakeResponse(200, (FIXTURE_SITE / filename).read_text(encoding="utf-8"))

    monkeypatch.setattr(requests.Session, "get", fake_get)
    return calls


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """Test config: no rate-limit sleeps, cache isolated to the test tmp dir."""
    return Config(rate_limit_seconds=0, cache_dir=tmp_path / "cache")


def load_fixture(name: str) -> str:
    return (FIXTURE_SITE / name).read_text(encoding="utf-8")
