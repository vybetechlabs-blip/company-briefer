"""Typer CLI: `company-briefer brief <domain>`."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import Annotated

import typer

from company_briefer.briefer import build_brief
from company_briefer.config import Config
from company_briefer.fetcher import RobotsUnavailableError
from company_briefer.models import BriefResult
from company_briefer.synthesize import api_key_present

app = typer.Typer(
    help="Polite, bounded pre-call research briefs from a company's public marketing pages.",
    no_args_is_help=True,
    add_completion=False,
)

_SKIP_NOTICE = "synthesis skipped — set ANTHROPIC_API_KEY and pass --llm to generate a brief"


def _utf8_console() -> None:
    """Keep output printable on legacy consoles (e.g. cp1252 on Windows).

    Fetched page titles are arbitrary unicode; without this, printing them
    crashes on terminals whose default encoding cannot represent them.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(Exception):
                reconfigure(encoding="utf-8", errors="replace")


@app.callback()
def main() -> None:
    """company-briefer: pre-call research briefs from public signals only."""
    _utf8_console()


@app.command()
def brief(
    domain: Annotated[str, typer.Argument(help="Company domain or URL, e.g. example.com")],
    llm: Annotated[
        bool,
        typer.Option(
            "--llm",
            help="Synthesize a Brief with one Anthropic API call (requires ANTHROPIC_API_KEY).",
        ),
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit the full BriefResult as JSON on stdout.")
    ] = False,
    out: Annotated[
        Path | None, typer.Option("--out", help="Also write the JSON result to this file.")
    ] = None,
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Bypass the on-disk HTML cache.")
    ] = False,
) -> None:
    """Fetch a company's public marketing pages and produce a research brief."""
    if llm and not api_key_present():
        typer.echo(
            "--llm requested but ANTHROPIC_API_KEY is not set; emitting evidence only.",
            err=True,
        )

    try:
        result = build_brief(domain, Config(), llm=llm, use_cache=not no_cache)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except RobotsUnavailableError as exc:
        typer.echo(
            f"error: cannot read robots.txt ({exc}); refusing to fetch any page from this site",
            err=True,
        )
        raise typer.Exit(code=3) from exc

    if out is not None:
        out.write_text(result.model_dump_json(indent=2), encoding="utf-8")

    if json_output:
        typer.echo(result.model_dump_json(indent=2))
    else:
        _render_human(result)

    if not result.evidence.pages:
        typer.echo("no pages could be fetched — see notes above", err=True)
        raise typer.Exit(code=1)


def _render_human(result: BriefResult) -> None:
    typer.echo(f"domain: {result.domain}")
    typer.echo(f"pages fetched: {len(result.evidence.pages)}")
    for page in result.evidence.pages:
        title = page.title or "(no title)"
        typer.echo(f"  - {page.url}  [{title}]")
    if result.evidence.robots_notes:
        typer.echo("notes:")
        for note in result.evidence.robots_notes:
            typer.echo(f"  - {note}")

    if result.brief is None:
        if result.synthesis_status in ("skipped_not_requested", "skipped_no_api_key"):
            typer.echo(_SKIP_NOTICE)
        elif result.synthesis_status == "failed":
            typer.echo("synthesis failed — the evidence above is still complete")
        return

    b = result.brief
    typer.echo("")
    typer.echo("positioning:")
    typer.echo(f"  {b.positioning}")
    _render_list("icp guess", b.icp_guess)
    _render_list("value props", b.value_props)
    _render_list("hooks", b.hooks)
    _render_list("signals observed", b.signals_observed)
    _render_list("sources", b.sources)
    typer.echo(f"confidence: {b.confidence.level} — {b.confidence.rationale}")
    if b.notes:
        typer.echo(f"notes: {b.notes}")


def _render_list(label: str, items: list[str]) -> None:
    typer.echo(f"{label}:")
    for item in items:
        typer.echo(f"  - {item}")


if __name__ == "__main__":  # pragma: no cover
    app()
