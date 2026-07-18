"""Synthesis: mocked Anthropic client only — valid, fenced, malformed, no-key, API error."""

from __future__ import annotations

import json
from typing import Any

import anthropic
import pytest

from company_briefer.config import Config
from company_briefer.models import Evidence
from company_briefer.synthesize import build_user_prompt, parse_brief, synthesize

VALID_BRIEF: dict[str, Any] = {
    "positioning": "Acme Signals positions itself as revenue intelligence for B2B teams.",
    "icp_guess": ["Sales leaders at fast-growing B2B SaaS companies"],
    "value_props": ["Deal-level win probability, explained in plain English"],
    "hooks": ["They emphasize forecast trust — ask how Monday forecast calls run today"],
    "signals_observed": ["Claims 400+ revenue teams", "Seat-based pricing from $49"],
    "sources": ["https://example.com/", "https://example.com/pricing"],
    "confidence": {"level": "medium", "rationale": "Three marketing pages, consistent story"},
    "notes": None,
}

EVIDENCE = Evidence(domain="https://example.com", pages=[], robots_notes=[])


class FakeBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [FakeBlock(text)]


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch, reply: str, captured: dict[str, Any] | None = None
) -> None:
    class FakeMessages:
        def create(self, **kwargs: Any) -> FakeMessage:
            if captured is not None:
                captured.update(kwargs)
            return FakeMessage(reply)

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)


class TestParseBrief:
    def test_valid_json(self) -> None:
        brief = parse_brief(json.dumps(VALID_BRIEF))
        assert brief is not None
        assert brief.confidence.level == "medium"

    def test_fenced_json(self) -> None:
        fenced = "```json\n" + json.dumps(VALID_BRIEF) + "\n```"
        assert parse_brief(fenced) is not None

    def test_json_with_surrounding_prose(self) -> None:
        noisy = "Here is the brief:\n" + json.dumps(VALID_BRIEF) + "\nHope that helps!"
        assert parse_brief(noisy) is not None

    def test_malformed_json_returns_none(self) -> None:
        assert parse_brief("{not valid json") is None

    def test_schema_violation_returns_none(self) -> None:
        assert parse_brief(json.dumps({"positioning": "x"})) is None

    def test_unknown_extra_field_returns_none(self) -> None:
        assert parse_brief(json.dumps({**VALID_BRIEF, "invented_field": 1})) is None


class TestSynthesize:
    def test_no_api_key_skips_cleanly(self, config: Config) -> None:
        brief, status = synthesize(EVIDENCE, config)
        assert brief is None
        assert status == "skipped_no_api_key"

    def test_valid_reply_yields_brief(
        self, monkeypatch: pytest.MonkeyPatch, config: Config
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
        captured: dict[str, Any] = {}
        _install_fake_client(monkeypatch, json.dumps(VALID_BRIEF), captured)
        brief, status = synthesize(EVIDENCE, config)
        assert status == "ok"
        assert brief is not None
        assert brief.positioning.startswith("Acme Signals")
        assert captured["model"] == config.model
        assert "Never invent" in captured["system"]

    def test_malformed_reply_fails_without_crashing(
        self, monkeypatch: pytest.MonkeyPatch, config: Config
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
        _install_fake_client(monkeypatch, "I'm sorry, I can't produce JSON today.")
        brief, status = synthesize(EVIDENCE, config)
        assert brief is None
        assert status == "failed"

    def test_api_error_fails_without_crashing(
        self, monkeypatch: pytest.MonkeyPatch, config: Config
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")

        class FakeMessages:
            def create(self, **kwargs: Any) -> None:
                raise anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]

        class FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self.messages = FakeMessages()

        monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
        brief, status = synthesize(EVIDENCE, config)
        assert brief is None
        assert status == "failed"


def test_user_prompt_embeds_evidence_and_grounding_ask() -> None:
    prompt = build_user_prompt(EVIDENCE)
    assert "https://example.com" in prompt
    assert "Produce the brief JSON now." in prompt
