"""Pydantic models for the evidence bundle and the synthesized brief."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _StrictModel(BaseModel):
    """Base for all models: unknown fields are an error, never silently dropped."""

    model_config = ConfigDict(extra="forbid")


class PageContent(_StrictModel):
    """Extracted, scrubbed content of a single fetched marketing page."""

    url: str
    status: int
    title: str | None = None
    meta_description: str | None = None
    headings: list[str] = []
    nav_labels: list[str] = []
    main_text: str = ""
    fetched_at: datetime


class Evidence(_StrictModel):
    """Everything actually observed for a domain: scrubbed pages plus crawl notes."""

    domain: str
    pages: list[PageContent] = []
    robots_notes: list[str] = []


class Confidence(_StrictModel):
    level: Literal["low", "medium", "high"]
    rationale: str


class Brief(_StrictModel):
    """LLM-synthesized positioning brief, grounded only in the supplied Evidence."""

    positioning: str
    icp_guess: list[str]
    value_props: list[str]
    hooks: list[str]
    signals_observed: list[str]
    sources: list[str]
    confidence: Confidence
    notes: str | None = None


SynthesisStatus = Literal[
    "ok",
    "skipped_not_requested",
    "skipped_no_api_key",
    "failed",
    "rejected_unfetched_source",
]


class BriefResult(_StrictModel):
    """Final output: evidence always present; brief only when synthesis ran and parsed."""

    domain: str
    evidence: Evidence
    brief: Brief | None = None
    synthesis_status: SynthesisStatus
