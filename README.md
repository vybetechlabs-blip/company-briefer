# company-briefer

Give it a domain; get a grounded pre-call research brief built **only from that
company's public marketing pages** — positioning, likely ICP, value props, and
outreach hooks, every claim traceable to a fetched URL.

It exists because pre-call research is usually either manual page-skimming or a
scraper that hoovers up far more than it should. `company-briefer` does the
narrow, polite version: a bounded fetch of a handful of standard marketing
paths, deterministic extraction of positioning signals, and an optional single
LLM call that is hard-scoped to what was actually observed. **No contact data,
ever** — emails and phone numbers are scrubbed before anything is stored,
printed, or sent to a model.

```text
domain ──> robots.txt ──> bounded fetch (≤8 allowlisted paths, rate-limited, cached)
       ──> extract (title / meta / h1–h3 / nav & CTA labels / marketing copy)
       ──> scrub (emails + phone numbers removed)
       ──> Evidence bundle ──> [optional: one LLM call] ──> Brief
```

## Install

```bash
git clone https://github.com/vybetechlabs-blip/company-briefer.git
cd company-briefer
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

Requires Python 3.11+.

## Quickstart

```bash
# Evidence bundle only — no API key needed, fully deterministic
company-briefer brief example.com

# Full JSON result (evidence + synthesis status)
company-briefer brief example.com --json

# With LLM synthesis (one Anthropic API call)
export ANTHROPIC_API_KEY=sk-ant-...
company-briefer brief example.com --llm

# Write the result to a file, skip the HTML cache
company-briefer brief example.com --llm --json --out brief.json --no-cache
```

Without a key (or without `--llm`) the tool still emits the complete evidence
bundle plus a clear notice:
`synthesis skipped — set ANTHROPIC_API_KEY and pass --llm to generate a brief`.

### Worked example

[`examples/sample_brief.json`](examples/sample_brief.json) is a real, checked-in
run against the synthetic fixture site in `tests/fixtures/site/` (a fake B2B
SaaS company, served over local HTTP). Highlights of the synthesized brief:

```json
{
  "positioning": "Acme Signals positions itself as a revenue intelligence platform for B2B teams ...",
  "hooks": [
    "Reference their 'forecasting without the folklore' and 'forecast theater' framing ...",
    "Note they're trusted by over 400 revenue teams — a signal of traction to reference in outreach"
  ],
  "confidence": {
    "level": "medium",
    "rationale": "Clear positioning and pricing across three pages, but product/platform and customer detail pages were blocked or missing."
  }
}
```

Note the evidence in the same file: the pricing page's seeded email and phone
number appear only as `[redacted]`, and the robots-disallowed paths were never
requested.

## Responsible crawling

These are deliberate design choices, not defaults you can flip off:

- **robots.txt is always honored.** Disallowed paths are skipped and noted in
  the output. There is deliberately **no override flag** — none will be added.
- **Bounded, targeted fetch — not a spider.** Only a fixed allowlist of common
  marketing paths (`/`, `/about`, `/product`, `/products`, `/pricing`,
  `/solutions`, `/customers`, `/platform`) on the same origin, capped at 8
  pages by default (hard ceiling of 16). Discovered links are never followed,
  so the crawl cannot leave the target domain.
- **Descriptive User-Agent.** Every request identifies the tool and links back
  to this repository, so site owners can see exactly what fetched their pages
  and why.
- **Rate-limited and patient.** A configurable delay (default 1s) between
  requests, a 10s timeout, and at most one retry with backoff.
- **Cached.** Fetched HTML is cached on disk (gitignored), so repeat runs
  don't re-hammer the same site. `--no-cache` forces a refetch.
- **No contact data, ever.** Contact/team/staff pages are not in the allowlist,
  and a scrub pass removes emails and phone numbers from every extracted field
  before the evidence bundle is assembled — nothing downstream (terminal, JSON,
  LLM) ever sees them.

## Output schema

The top-level result (`BriefResult`):

| field | type | notes |
|---|---|---|
| `domain` | str | normalized origin, e.g. `https://example.com` |
| `evidence` | `Evidence` | always present, fully deterministic |
| `brief` | `Brief \| null` | present only when synthesis ran and validated |
| `synthesis_status` | str | `ok`, `skipped_not_requested`, `skipped_no_api_key`, `failed` |

`Evidence` holds `pages` (per-page `url`, `status`, `title`,
`meta_description`, `headings`, `nav_labels`, scrubbed `main_text`,
`fetched_at`) and `robots_notes` (what was skipped and why).

`Brief` (all grounded in the evidence, validated with Pydantic, unknown fields
rejected):

| field | type | notes |
|---|---|---|
| `positioning` | str | one-paragraph positioning summary |
| `icp_guess` | list[str] | likely ideal customer profiles |
| `value_props` | list[str] | as stated or clearly implied on the pages |
| `hooks` | list[str] | outreach angles tied to specific observed signals |
| `signals_observed` | list[str] | concrete things seen on the pages |
| `sources` | list[str] | URLs from the evidence that informed the brief |
| `confidence` | `{level, rationale}` | `low` / `medium` / `high` plus a one-line reason |
| `notes` | str \| null | caveats (blocked pages, self-reported claims, …) |

## Configuration

Defaults live in [`company_briefer/config.py`](company_briefer/config.py) as a
validated Pydantic model:

| knob | default | bounds |
|---|---|---|
| `timeout_seconds` | 10.0 | > 0 |
| `rate_limit_seconds` | 1.0 | ≥ 0 |
| `max_pages` | 8 | 1–16 (hard cap) |
| `path_allowlist` | 8 marketing paths | — |
| `user_agent` | descriptive UA with repo URL | — |
| `model` | `claude-opus-4-8` | — |
| `max_tokens` | 4096 | ≥ 256 |
| `max_page_chars` | 6000 per page | ≥ 500 |
| `cache_dir` | `.cache/company-briefer` | gitignored |

Programmatic use can override any of them:

```python
from company_briefer.briefer import build_brief
from company_briefer.config import Config

result = build_brief("example.com", Config(max_pages=4, rate_limit_seconds=2.0), llm=False)
print(result.evidence.model_dump_json(indent=2))
```

## LLM synthesis (optional)

The deterministic gather+extract pipeline is the product; the LLM layer is an
optional summarizer on top of it.

- Enabled only with `--llm` **and** `ANTHROPIC_API_KEY` in the environment
  (see `.env.example`; the key is read from the environment only and never
  written anywhere).
- Exactly one API call per run. The prompt instructs the model to synthesize
  only from the supplied evidence, cite source URLs, and mark low-confidence
  inferences as such.
- Model output is parsed defensively (code fences, stray prose, malformed
  JSON) and validated through Pydantic with `extra="forbid"`. On any failure
  the evidence bundle is still emitted with `synthesis_status: "failed"`.

## Development

```bash
pip install -e ".[dev]"
make check        # ruff (lint + format) + mypy --strict + pytest with ≥90% coverage
```

The test suite runs **zero network requests**: every test works against saved
HTML fixtures with the HTTP layer mocked, and an autouse guard makes any
unmocked HTTP attempt fail the test. The Anthropic client is likewise mocked —
no API calls in tests.

Exit codes: `0` success, `1` no pages could be fetched, `2` invalid domain
input.

## License

MIT
