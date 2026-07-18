"""Turn raw HTML into structured page content with BeautifulSoup. Pure, no IO.

Pulls the positioning signals a human would skim for: title, meta description,
h1-h3 headings, nav/CTA labels, and the main visible marketing copy. Scripts,
styles, and page chrome (nav/header/footer) are dropped from the body text.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup, Tag

from company_briefer.models import PageContent

_WHITESPACE_RE = re.compile(r"\s+")
_STRIP_TAGS = ["script", "style", "noscript", "template", "svg", "iframe"]
_CTA_CLASS_HINTS = ("btn", "button", "cta")


def _clean(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _element_classes(element: Any) -> str:
    classes = element.get("class") or []
    if isinstance(classes, list):
        return " ".join(str(c) for c in classes).lower()
    return str(classes).lower()


def extract_page(
    url: str,
    status: int,
    html: str,
    fetched_at: datetime,
    *,
    max_text_chars: int = 6000,
) -> PageContent:
    """Extract structured content from one page's HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    title = _clean(soup.title.get_text()) if soup.title else None

    meta_description: str | None = None
    meta = soup.find("meta", attrs={"name": "description"})
    if isinstance(meta, Tag):
        content = meta.get("content")
        if isinstance(content, str):
            meta_description = _clean(content) or None

    headings = [
        cleaned for h in soup.find_all(["h1", "h2", "h3"]) if (cleaned := _clean(h.get_text()))
    ]

    nav_labels: list[str] = []
    seen: set[str] = set()

    def _add_label(text: str) -> None:
        cleaned = _clean(text)
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            nav_labels.append(cleaned)

    for nav in soup.find_all("nav"):
        for link in nav.find_all("a"):
            _add_label(link.get_text())
    for element in soup.find_all(["a", "button"]):
        if any(hint in _element_classes(element) for hint in _CTA_CLASS_HINTS):
            _add_label(element.get_text())

    body = soup.find("main") or soup.body
    if isinstance(body, Tag):
        for tag in body.find_all(["nav", "header", "footer", "aside"]):
            tag.decompose()
        main_text = _clean(body.get_text(separator=" "))
    else:
        main_text = _clean(soup.get_text(separator=" "))
    if len(main_text) > max_text_chars:
        main_text = main_text[:max_text_chars].rstrip() + " …"

    return PageContent(
        url=url,
        status=status,
        title=title or None,
        meta_description=meta_description,
        headings=headings,
        nav_labels=nav_labels,
        main_text=main_text,
        fetched_at=fetched_at,
    )
