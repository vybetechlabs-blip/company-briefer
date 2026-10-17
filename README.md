# company-briefer

[![CI](https://github.com/vybetechlabs-blip/company-briefer/actions/workflows/ci.yml/badge.svg)](https://github.com/vybetechlabs-blip/company-briefer/actions/workflows/ci.yml)

Give it a domain and get a pre-call research brief built only from that company's public marketing pages: positioning, likely customers, value propositions and outreach angles.

## Problem and result
Preparing for a sales call usually means skimming a website by hand or running a scraper that collects far more than it should. company-briefer does the narrow version. It reads at most 8 fixed marketing paths on one origin, with a hard ceiling of 16, one second apart. It removes email addresses and phone numbers before it builds the evidence or writes anything to disk. It stops if robots.txt cannot be read, and it never follows a redirect that leaves the origin or leads into a path robots.txt disallows.

The result is an evidence bundle that needs no API key, plus an optional brief from one model call. The brief is validated against a schema, and every source it cites must be a page that was fetched. The committed example, `examples/sample_brief.json`, cites 3 fetched pages and holds 2 redacted contact strings. The suite has 115 tests, makes no network requests and covers 98.9% of the code against a 90% gate.

### How it works
A run goes through these stages in order, and several of them can stop it.

```
domain ──> robots.txt (unreadable: stop, exit code 3)
       ──> bounded fetch (at most 8 allowlisted paths, one second apart)
             a redirect to another origin or into a disallowed path: skip that path, note the target
       ──> extract (title, meta description, h1 to h3, nav and CTA labels, main text)
       ──> scrub (emails and phone numbers removed) ──> cache (scrubbed pages only)
       ──> evidence bundle
       ──> optional: one LLM call ──> source check ──> brief
```

`fetcher.py` is the only module that does HTTP, and `cache.py` is the only one that writes pages to disk. `crawler.py`, `extractor.py` and `scrub.py` hold the logic that needs no network, `synthesize.py` makes the optional call, `briefer.py` ties the stages together and `cli.py` is the command line.

## Decision log
**1. A fixed list of marketing paths, not a crawl.**
Chosen: the tool requests only `/`, `/about`, `/product`, `/products`, `/pricing`, `/solutions`, `/customers` and `/platform`, each built from the origin plus the path. A run stops at 8 pages, and the configuration does not accept a cap above 16.
Rejected: following links found on pages, which can lead anywhere, and fetching contact, team or staff pages, which are mostly names and contact details.
Known limits: a site that keeps its positioning under other paths yields fewer pages, and the list assumes common English path names.

**2. One-second spacing between requests.**
Chosen: the default delay is 1.0 second between requests, with a 10-second timeout and one retry after twice the delay on a connection error or an HTTP 5xx. A full run of 8 pages plus robots.txt takes at least 8 seconds. The delay is a `Config` value that cannot go below zero, and the command line has no flag for it. Every request carries a User-Agent that names the tool and links to this repository, so a site owner can see what fetched their pages.
Rejected: parallel fetching, which would hit a small company's site with a burst.
Cost: a run is slow on purpose.

**3. Emails and phone numbers are removed before anything is stored or printed.**
Chosen: every text field of every page passes through a scrub that replaces emails and phone-like numbers (eight digits or more, with separators) with a redaction marker. The terminal output, the JSON, the model prompt and the on-disk cache are all built from the scrubbed pages, and the HTML as fetched is never written anywhere. `--no-cache` skips the cache, which is gitignored.
Rejected: leaving the data in and asking the model to ignore it, and relying on the path list alone to keep it out. Also rejected: caching the HTML as fetched, which the first release did (commit `8e0a0b5`), and scrubbing the raw markup before caching it, because an email written as an HTML entity survives that and is only caught after the extractor decodes it. A probe run after the repo was public found the cache, and `tests/test_cache.py` reproduces it.
Known limits: the scrub is pattern-based. Names, street addresses and social profile links are not removed, and a number written out in words is not matched. A `.cache` folder left by an earlier version holds HTML as fetched and is never read again, so delete it.

**4. Works without a key, with one validated model call behind a flag.**
Chosen: a plain run needs no key and returns the evidence bundle. With `--llm` and `ANTHROPIC_API_KEY` set, it makes exactly one model call. The reply is parsed defensively and validated against a schema that rejects unknown fields. A brief whose sources are not all fetched URLs is rejected rather than repaired (decision 7). On any failure the evidence is still returned. The model name is a default in `company_briefer/config.py`.
Rejected: a model call on by default, which would put cost and run-to-run variation into every use, and a multi-step agent loop, which is harder to check than one call.

**5. If robots.txt cannot be read, the run stops.**
Chosen: a connection error, a timeout, an HTTP 5xx or other unusable answer, or a redirect to another origin means no page is requested. The command prints the reason, exits with code 3 and writes no result. An HTTP 4xx means the site publishes no robots.txt, and the run continues with a note in the evidence.
Rejected: the first release's behavior, which treated an unreadable robots.txt as permission and fetched every allowlisted path (commit `8e0a0b5`, where a test pinned that behavior). A probe run after the repo was public found it.
Known limits: a short outage on the target site stops the run, so run it again later.

**6. Redirects are followed only inside the origin, and only where robots.txt allows.**
Chosen: a redirect inside the same origin (scheme, host and port) is followed one hop at a time, and each target is checked against robots.txt before it is requested. A redirect to any other origin, or into a path robots.txt disallows, is never requested. That path is skipped, and the evidence notes the target without its query string.
Rejected: following every redirect, as the first release did. A page that redirected to another host was fetched without reading that host's robots.txt, and its content was recorded under the original URL. A redirect inside the origin into a disallowed path was fetched too, because robots.txt was checked for the path the tool asked for and not for where it led. A probe run after the repo was public found both, and `tests/test_redirects.py` reproduces them.
Known limits: a redirect from `http://example.com` to `https://example.com` counts as another origin, and so does one from a bare domain to its `www` host. Pass the final address.

**7. Sources are one list per brief, and each must be a fetched URL.**
Chosen: a brief has a single `sources` list for the whole brief. Every URL in it must be one of the URLs fetched in that run. URLs are compared after ignoring one trailing slash and the case of the scheme and the host, and nothing else, and the sources are not rewritten. A brief that fails the check is rejected, not repaired, with status `rejected_unfetched_source`, and the evidence is still returned.
Deferred: citing a source for each claim. It needs a different output schema and a check for every claim, and it was left for a later version.

## How AI was used
Placeholder: the author writes this section. <!-- OWNER: replace this section with your own text before the repo is shared. -->

## Run it locally
Requires Python 3.11 or newer (CI runs 3.11, 3.12 and 3.13). You need [git](https://git-scm.com/) and [uv](https://docs.astral.sh/uv/). The first run creates a virtual environment and installs the dependencies on its own.

```bash
git clone https://github.com/vybetechlabs-blip/company-briefer.git
cd company-briefer
uv run company-briefer brief example.com
```

That prints the evidence bundle and a notice that synthesis was skipped. It needs no key and no account. Other commands:

```bash
uv run company-briefer brief example.com --json            # the full result as JSON
uv run company-briefer brief example.com --out brief.json  # also write the JSON to a file
uv run company-briefer brief example.com --no-cache        # refetch instead of reading .cache
uv run --extra dev pytest                                  # 115 tests, no network
uv run --extra dev ruff check company_briefer tests
uv run --extra dev mypy company_briefer
```

Without uv, create a virtual environment, run `pip install -e .` inside it, and then call `company-briefer` directly from that environment.

### Model-backed briefs
Set the key in your shell environment and pass the flag. The tool makes one Anthropic API call. The key is read from the environment and written nowhere, and `.env.example` names it.
```bash
export ANTHROPIC_API_KEY=<your key>
uv run company-briefer brief example.com --llm
```

Without a key, `--llm` prints a notice and returns the evidence only, so the same command is safe to run before a key is set.

Exit codes: `0` success, `1` no pages could be fetched, `2` invalid domain input, `3` robots.txt could not be read.

### Output schema
The top-level result, `BriefResult`, has the four fields below, and it is what `--json` prints.

| field | type | notes |
|---|---|---|
| `domain` | str | normalized origin, for example `https://example.com` |
| `evidence` | `Evidence` | always present, fully deterministic |
| `brief` | `Brief` or null | present only when synthesis ran, validated and passed the source check |
| `synthesis_status` | str | `ok`, `skipped_not_requested`, `skipped_no_api_key`, `failed`, `rejected_unfetched_source` |

`Evidence` holds `pages` (per page: `url`, `status`, `title`, `meta_description`, `headings`, `nav_labels`, scrubbed `main_text`, `fetched_at`) and `robots_notes`: what was skipped and why, an absent robots.txt, and any redirect that was not followed.

`Brief` is validated with Pydantic, unknown fields are rejected, and every source it lists must have been fetched during the same run.

| field | type | notes |
|---|---|---|
| `positioning` | str | one-paragraph positioning summary |
| `icp_guess` | list of str | likely ideal customer profiles |
| `value_props` | list of str | as stated or clearly implied on the pages |
| `hooks` | list of str | outreach angles tied to specific observed signals |
| `signals_observed` | list of str | concrete things seen on the pages |
| `sources` | list of str | URLs from the evidence; each must have been fetched |
| `confidence` | `level`, `rationale` | `low`, `medium` or `high`, plus a one-line reason |
| `notes` | str or null | caveats such as blocked pages |

### Configuration
Defaults live in [`company_briefer/config.py`](company_briefer/config.py) as a validated Pydantic model, and every bound below is checked when the model is built.

| knob | default | bounds |
|---|---|---|
| `timeout_seconds` | 10.0 | above 0 |
| `rate_limit_seconds` | 1.0 | 0 or more |
| `max_pages` | 8 | 1 to 16 |
| `path_allowlist` | the 8 paths in decision 1 | none |
| `user_agent` | names the tool and links to this repository | none |
| `model` | `claude-opus-4-8` | none |
| `max_tokens` | 4096 | 256 or more |
| `max_page_chars` | 6000 per page | 500 or more |
| `cache_dir` | `.cache/company-briefer` | scrubbed pages only; gitignored |

The command line uses the defaults. Library code can override them:
```python
from company_briefer.briefer import build_brief
from company_briefer.config import Config

result = build_brief("example.com", Config(max_pages=4, rate_limit_seconds=2.0), llm=False)
print(result.evidence.model_dump_json(indent=2))
```

`build_brief` raises `company_briefer.fetcher.RobotsUnavailableError` when robots.txt cannot be read, before any page is requested.

License: MIT, see [LICENSE](LICENSE). The example brief was generated from the synthetic fixture site in `tests/fixtures/site/`, a made-up company with a reserved 555 phone number and an `.example` email domain.

## Status
**Status: Complete.** The 115 tests pass, and CI runs ruff, mypy and pytest on Python 3.11, 3.12 and 3.13. Known limits are listed in the decision log.
