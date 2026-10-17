"""Optional LLM synthesis: Evidence in, schema-validated Brief out.

One Anthropic API call, made only when the caller opts in with --llm and
ANTHROPIC_API_KEY is set in the environment. The prompt hard-scopes the model
to the supplied evidence; output is parsed defensively (code fences, stray
prose, malformed JSON) and validated through Pydantic before anything is
returned. On any failure the caller still gets the evidence bundle.
"""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit, urlunsplit

import anthropic
from pydantic import ValidationError

from company_briefer.config import Config
from company_briefer.models import Brief, Evidence, SynthesisStatus

_SYSTEM_PROMPT = """\
You are a pre-call research analyst. You will receive evidence extracted from a
company's public marketing pages. Produce a research brief as a single JSON
object and nothing else.

Rules:
- Synthesize ONLY from the supplied evidence. Never invent products, customers,
  metrics, names, or facts that are not present in it.
- If the evidence is thin, say so: keep lists short, set confidence to "low",
  and explain the gap in the rationale.
- Mark low-confidence inferences as such ("likely", "appears to") instead of
  stating them as fact.
- "sources" must contain only URLs that appear in the evidence.
- "hooks" are outreach angles; each must be grounded in a specific observed
  signal, never in outside knowledge.
- Output raw JSON only: no markdown fences, no commentary before or after.

JSON shape:
{
  "positioning": "one-paragraph summary of how the company positions itself",
  "icp_guess": ["likely ideal customer profiles, grounded in observed signals"],
  "value_props": ["value propositions as stated or clearly implied on the pages"],
  "hooks": ["outreach angles tied to specific observed signals"],
  "signals_observed": ["concrete things seen on the pages"],
  "sources": ["URLs from the evidence that informed this brief"],
  "confidence": {"level": "low|medium|high", "rationale": "one line"},
  "notes": "optional caveats, or null"
}
"""


def api_key_present() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def build_user_prompt(evidence: Evidence) -> str:
    return (
        f"Evidence for {evidence.domain} (JSON; one object per fetched page):\n"
        f"{evidence.model_dump_json(indent=2)}\n\n"
        "Produce the brief JSON now."
    )


def _extract_json(text: str) -> str:
    """Best-effort recovery of a JSON object from model output."""
    stripped = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fenced:
        stripped = fenced.group(1).strip()
    if not stripped.startswith("{"):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end > start:
            stripped = stripped[start : end + 1]
    return stripped


def parse_brief(text: str) -> Brief | None:
    """Parse model output into a Brief; None if it cannot be validated."""
    try:
        data = json.loads(_extract_json(text))
        return Brief.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        return None


def _normalize_url(url: str) -> str:
    """Make two spellings of one URL compare equal, and nothing more.

    Three differences are ignored: one trailing slash on the path, and the case of
    the scheme and of the host. Path case, query, fragment, scheme and port still
    have to match.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    path = parts.path.removesuffix("/")
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, parts.query, parts.fragment)
    )


def unfetched_sources(brief: Brief, evidence: Evidence) -> list[str]:
    """Sources in *brief* that are not one of the URLs fetched into *evidence*.

    URLs are compared after `_normalize_url`; the sources themselves are not rewritten.
    """
    fetched = {_normalize_url(page.url) for page in evidence.pages}
    return [source for source in brief.sources if _normalize_url(source) not in fetched]


def synthesize(evidence: Evidence, config: Config) -> tuple[Brief | None, SynthesisStatus]:
    """Run the single synthesis call. Never raises on model output problems.

    A brief that cites any source other than a fetched URL (a trailing slash and
    the case of scheme and host aside) is rejected, not repaired: the prompt asks
    for evidence URLs only, and this enforces it.
    """
    if not api_key_present():
        return None, "skipped_no_api_key"
    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=config.model,
            max_tokens=config.max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_user_prompt(evidence)}],
        )
    except anthropic.APIError:
        return None, "failed"
    text = "".join(block.text for block in response.content if block.type == "text")
    brief = parse_brief(text)
    if brief is None:
        return None, "failed"
    if unfetched_sources(brief, evidence):
        return None, "rejected_unfetched_source"
    return brief, "ok"
