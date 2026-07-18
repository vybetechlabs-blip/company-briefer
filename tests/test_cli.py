"""CLI: human output, --json, --out, no-key skip notice, exit codes. CliRunner only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests
from typer.testing import CliRunner

from company_briefer import cli
from company_briefer.config import Config

runner = CliRunner()


@pytest.fixture(autouse=True)
def _test_config(monkeypatch: pytest.MonkeyPatch, config: Config) -> None:
    """CLI builds its own Config(); swap in the test config (no sleeps, tmp cache)."""
    monkeypatch.setattr(cli, "Config", lambda: config)


def test_help_is_complete() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    result = runner.invoke(cli.app, ["brief", "--help"])
    assert result.exit_code == 0
    for option in ("--llm", "--json", "--out", "--no-cache"):
        assert option in result.output


def test_human_output_and_skip_notice(fake_site: list[dict[str, Any]]) -> None:
    result = runner.invoke(cli.app, ["brief", "example.com"])
    assert result.exit_code == 0
    assert "domain: https://example.com" in result.output
    assert "pages fetched: 3" in result.output
    assert "synthesis skipped" in result.output
    assert "ANTHROPIC_API_KEY" in result.output


def test_json_output_is_valid_and_complete(fake_site: list[dict[str, Any]]) -> None:
    result = runner.invoke(cli.app, ["brief", "example.com", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["domain"] == "https://example.com"
    assert payload["brief"] is None
    assert payload["synthesis_status"] == "skipped_not_requested"
    assert len(payload["evidence"]["pages"]) == 3


def test_out_writes_json_file(fake_site: list[dict[str, Any]], tmp_path: Path) -> None:
    target = tmp_path / "result.json"
    result = runner.invoke(cli.app, ["brief", "example.com", "--out", str(target)])
    assert result.exit_code == 0
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["domain"] == "https://example.com"


def test_llm_without_key_warns_and_still_emits_evidence(
    fake_site: list[dict[str, Any]],
) -> None:
    result = runner.invoke(cli.app, ["brief", "example.com", "--llm"])
    assert result.exit_code == 0
    assert "ANTHROPIC_API_KEY is not set" in result.output
    assert "synthesis skipped" in result.output


def test_full_brief_renders_human_readably(
    fake_site: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """--llm with a mocked client: every Brief section reaches the terminal."""
    import anthropic

    from tests.test_synthesize import VALID_BRIEF, FakeMessage

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")

    class FakeMessages:
        def create(self, **kwargs: Any) -> FakeMessage:
            return FakeMessage(json.dumps(VALID_BRIEF))

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)

    result = runner.invoke(cli.app, ["brief", "example.com", "--llm"])
    assert result.exit_code == 0
    for section in ("positioning:", "icp guess:", "hooks:", "sources:", "confidence:"):
        assert section in result.output
    assert "Acme Signals positions itself" in result.output


def test_invalid_domain_exits_2() -> None:
    result = runner.invoke(cli.app, ["brief", "not a domain!!"])
    assert result.exit_code == 2
    assert "error:" in result.output


def test_nothing_fetched_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse_everything(self: Any, url: str, **kw: Any) -> Any:
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(requests.Session, "get", refuse_everything)
    result = runner.invoke(cli.app, ["brief", "example.com"])
    assert result.exit_code == 1
