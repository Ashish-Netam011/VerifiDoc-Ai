"""PDF text extraction with PyMuPDF, preserving page boundaries.

Extraction is deliberately strict: a page that cannot be read raises instead of
being dropped, so the caller never receives a document that looks complete but
has silently lost content.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


class PDFExtractionError(RuntimeError):
    """The file could not be opened or its text could not be extracted."""


@dataclass(frozen=True)
class ExtractedPage:
    """Text of one page, 1-indexed."""

    page_number: int
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass(frozen=True)
class ExtractedDocument:
    """All pages of a document, in reading order."""

    document_id: str
    filename: str
    page_count: int
    pages: tuple[ExtractedPage, ...]

    @property
    def char_count(self) -> int:
        return sum(page.char_count for page in self.pages)

    @property
    def has_text(self) -> bool:
        return any(page.text.strip() for page in self.pages)


def extract_pdf(path: Path, document_id: str, filename: str) -> ExtractedDocument:
    """Open ``path`` and return its pages, or raise :class:`PDFExtractionError`."""
    try:
        document = fitz.open(path)
    except Exception as exc:  # noqa: BLE001 - fitz raises varied exception types
        raise PDFExtractionError("The file is not a readable PDF.") from exc

    try:
        if document.is_encrypted and not document.authenticate(""):
            raise PDFExtractionError(
                "The PDF is password protected and cannot be processed."
            )

        page_count = document.page_count
        if page_count == 0:
            raise PDFExtractionError("The PDF contains no pages.")

        pages: list[ExtractedPage] = []
        for index in range(page_count):
            try:
                text = document.load_page(index).get_text("text") or ""
            except Exception as exc:  # noqa: BLE001 - per-page fitz failures
                raise PDFExtractionError(
                    f"Failed to extract text from page {index + 1}."
                ) from exc
            pages.append(ExtractedPage(page_number=index + 1, text=text))
    finally:
        document.close()

    logger.info(
        "Extracted %s pages (%s chars) from %s",
        page_count,
        sum(page.char_count for page in pages),
        document_id,
    )
    return ExtractedDocument(
        document_id=document_id,
        filename=filename,
        page_count=page_count,
        pages=tuple(pages),
    )
