"""Strip contact data (emails, phone numbers) from extracted text.

Hard rule for this project: no contact data is ever stored, printed, or sent
to the LLM. Every text field passes through this scrub before the Evidence
bundle is assembled, so incidentally-captured contact details on a marketing
page never survive extraction.
"""

from __future__ import annotations

import re

from company_briefer.models import PageContent

REDACTED = "[redacted]"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Phone-like sequences: optional country code, then at least 7 more digits with
# common separators. Requiring 8+ digits total keeps prices and years intact.
_PHONE_RE = re.compile(
    r"""
    (?<![\w/-])              # not glued to a word, path, or version string
    \+?\(?\d{1,4}\)?         # leading digits / country code
    (?:[\s().-]{0,3}\d){7,}  # at least 7 more digits with separators
    (?![\w-])
    """,
    re.VERBOSE,
)


def scrub_text(text: str) -> str:
    """Return *text* with emails and phone numbers replaced by a redaction marker."""
    text = _EMAIL_RE.sub(REDACTED, text)
    return _PHONE_RE.sub(REDACTED, text)


def scrub_page(page: PageContent) -> PageContent:
    """Return a copy of *page* with every text field scrubbed."""
    return page.model_copy(
        update={
            "title": scrub_text(page.title) if page.title else page.title,
            "meta_description": (
                scrub_text(page.meta_description) if page.meta_description else None
            ),
            "headings": [scrub_text(h) for h in page.headings],
            "nav_labels": [scrub_text(n) for n in page.nav_labels],
            "main_text": scrub_text(page.main_text),
        }
    )
