"""Orchestrator: domain -> robots -> bounded fetch -> extract -> scrub -> [synthesize]."""

from __future__ import annotations

import requests

from company_briefer.config import Config
from company_briefer.crawler import RobotsPolicy, normalize_origin, plan_fetch
from company_briefer.extractor import extract_page
from company_briefer.fetcher import Fetcher
from company_briefer.models import BriefResult, Evidence, PageContent
from company_briefer.scrub import scrub_page
from company_briefer.synthesize import synthesize


def build_brief(
    domain: str,
    config: Config | None = None,
    *,
    llm: bool = False,
    use_cache: bool = True,
) -> BriefResult:
    """Run the full pipeline for one domain and return a BriefResult.

    The deterministic gather+extract stages always run; the LLM synthesis
    stage runs only when *llm* is True and an API key is available. Raises
    `RobotsUnavailableError` before any page is requested when robots.txt cannot
    be read.
    """
    config = config or Config()
    origin = normalize_origin(domain)
    fetcher = Fetcher(config, use_cache=use_cache)

    robots_txt = fetcher.fetch_robots(origin)  # raises RobotsUnavailableError: fail-closed
    policy = RobotsPolicy(robots_txt, config.user_agent)
    notes: list[str] = []
    if robots_txt is None:
        notes.append("no robots.txt published (HTTP 4xx); proceeding with allowlisted paths only")

    urls, plan_notes = plan_fetch(origin, config.path_allowlist, policy, config.max_pages)
    notes.extend(plan_notes)

    pages: list[PageContent] = []
    for url in urls:
        try:
            fetched = fetcher.fetch_page(url)
        except requests.RequestException as exc:
            notes.append(f"fetch failed for {url}: {exc.__class__.__name__}")
            continue
        if fetched.redirect_to is not None:
            notes.append(
                f"skipped {url}: redirects to another origin ({fetched.redirect_to}); not followed"
            )
            continue
        if fetched.status != 200:
            notes.append(f"skipped {url}: HTTP {fetched.status}")
            continue
        page = extract_page(
            fetched.url,
            fetched.status,
            fetched.html,
            fetched.fetched_at,
            max_text_chars=config.max_page_chars,
        )
        pages.append(scrub_page(page))

    evidence = Evidence(domain=origin, pages=pages, robots_notes=notes)

    if not llm:
        return BriefResult(
            domain=origin, evidence=evidence, synthesis_status="skipped_not_requested"
        )

    brief, status = synthesize(evidence, config)
    return BriefResult(domain=origin, evidence=evidence, brief=brief, synthesis_status=status)
