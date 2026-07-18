"""Runtime configuration with validated, deliberately polite defaults."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_PATH_ALLOWLIST: tuple[str, ...] = (
    "/",
    "/about",
    "/product",
    "/products",
    "/pricing",
    "/solutions",
    "/customers",
    "/platform",
)


class Config(BaseModel):
    """Tunable knobs for the pipeline.

    The bounds are part of the politeness contract: the page cap cannot be
    raised past 16, the rate limit cannot go negative, and there is no switch
    anywhere to ignore robots.txt.
    """

    model_config = ConfigDict(extra="forbid")

    timeout_seconds: float = Field(default=10.0, gt=0)
    rate_limit_seconds: float = Field(default=1.0, ge=0)
    max_pages: int = Field(default=8, ge=1, le=16)
    path_allowlist: tuple[str, ...] = DEFAULT_PATH_ALLOWLIST
    user_agent: str = "company-briefer/0.1 (+https://github.com/vybetechlabs-blip/company-briefer)"
    model: str = "claude-opus-4-8"
    max_tokens: int = Field(default=4096, ge=256)
    max_page_chars: int = Field(default=6000, ge=500)
    cache_dir: Path = Path(".cache/company-briefer")
