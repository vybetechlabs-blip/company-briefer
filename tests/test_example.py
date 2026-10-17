"""The committed example brief: schema-valid, grounded in its own evidence, no contact data.

The README quotes numbers from this file (3 fetched pages, 2 redacted strings),
so they are asserted here and cannot drift unnoticed.
"""

from __future__ import annotations

import re
from pathlib import Path

from company_briefer.models import BriefResult
from company_briefer.synthesize import unfetched_sources

EXAMPLE = Path(__file__).parent.parent / "examples" / "sample_brief.json"


def _load() -> tuple[str, BriefResult]:
    raw = EXAMPLE.read_text(encoding="utf-8")
    return raw, BriefResult.model_validate_json(raw)


def test_example_is_a_valid_result_with_a_brief() -> None:
    _, result = _load()
    assert result.synthesis_status == "ok"
    assert result.brief is not None


def test_example_cites_only_fetched_pages() -> None:
    _, result = _load()
    assert result.brief is not None
    assert len(result.evidence.pages) == 3
    assert len(result.brief.sources) == 3
    assert unfetched_sources(result.brief, result.evidence) == []


def test_example_holds_two_redactions_and_no_contact_data() -> None:
    raw, _ = _load()
    assert raw.count("[redacted]") == 2
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", raw)
    assert not re.search(r"\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}", raw)
