"""On-disk cache of scrubbed pages.

Only the extracted, scrubbed `PageContent` is written, never the HTML as fetched,
so nothing on disk holds an email or phone number the pipeline removed. (Scrubbing
the raw markup instead would miss an email written as an HTML entity, which the
extractor decodes and the scrub then catches.) The key covers the URL and the text
limit the page was extracted with, so a changed limit never serves a stale page.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from company_briefer.models import PageContent


class PageCache:
    """Cache of scrubbed pages for repeat runs; a corrupt entry reads as a miss."""

    def __init__(self, directory: Path, max_page_chars: int) -> None:
        self.directory = directory
        self.max_page_chars = max_page_chars

    def _path(self, url: str) -> Path:
        key = f"{url}\n{self.max_page_chars}".encode()
        return self.directory / f"{hashlib.sha256(key).hexdigest()[:24]}.json"

    def read(self, url: str) -> PageContent | None:
        path = self._path(url)
        if not path.is_file():
            return None
        try:
            page = PageContent.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):  # pydantic's ValidationError is a ValueError
            return None
        return page if page.url == url else None

    def write(self, page: PageContent) -> None:
        path = self._path(page.url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page.model_dump_json(), encoding="utf-8")
