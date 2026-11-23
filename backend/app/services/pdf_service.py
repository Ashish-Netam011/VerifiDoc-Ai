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
class ExtractedTable:
    """A detected PDF table with page provenance and review status."""

    document_id: str
    filename: str
    page_number: int
    table_id: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str | None, ...], ...]
    status: str
    review_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "page_number": self.page_number,
            "table_id": self.table_id,
            "headers": list(self.headers),
            "rows": [list(row) for row in self.rows],
            "status": self.status,
            "review_reason": self.review_reason,
        }

    def as_search_text(self) -> str:
        status = "REVIEW REQUIRED" if self.status != "extracted" else "extracted"
        lines = [f"[Table {self.table_id}; {status}]"]
        if self.headers:
            lines.append(" | ".join(self.headers))
        lines.extend(" | ".join(cell or "" for cell in row) for row in self.rows)
        return "\n".join(lines)


@dataclass(frozen=True)
class ExtractedPage:
    """Text of one page, 1-indexed."""

    page_number: int
    text: str
    tables: tuple[ExtractedTable, ...] = ()

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

    @property
    def tables(self) -> tuple[ExtractedTable, ...]:
        return tuple(table for page in self.pages for table in page.tables)


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
            page_number = index + 1
            try:
                page = document.load_page(index)
                text = page.get_text("text") or ""
            except Exception as exc:  # noqa: BLE001 - per-page fitz failures
                raise PDFExtractionError(
                    f"Failed to extract text from page {page_number}."
                ) from exc
            tables = _extract_page_tables(
                page,
                document_id=document_id,
                filename=filename,
                page_number=page_number,
            )
            indexed_text = text
            if tables:
                indexed_text += "\n\n" + "\n\n".join(
                    table.as_search_text() for table in tables
                )
            pages.append(
                ExtractedPage(
                    page_number=page_number,
                    text=indexed_text,
                    tables=tuple(tables),
                )
            )
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


def _extract_page_tables(
    page: fitz.Page,
    *,
    document_id: str,
    filename: str,
    page_number: int,
) -> list[ExtractedTable]:
    """Extract detectable tables; uncertain structures remain explicitly flagged."""
    try:
        finder = page.find_tables()
    except Exception as exc:  # PyMuPDF table detection varies by page layout.
        logger.warning(
            "Table detection failed for document %s page %s: %s",
            document_id,
            page_number,
            exc,
        )
        return []

    tables: list[ExtractedTable] = []
    for index, table in enumerate(finder.tables, start=1):
        table_id = f"p{page_number:04d}-t{index:04d}"
        try:
            extracted = table.extract()
        except Exception as exc:
            logger.warning(
                "Table extraction failed for document %s page %s table %s: %s",
                document_id,
                page_number,
                table_id,
                exc,
            )
            tables.append(
                ExtractedTable(
                    document_id, filename, page_number, table_id, (), (), "failed",
                    "PyMuPDF could not extract the detected table.",
                )
            )
            continue

        extracted_rows = extracted or []
        column_count = int(getattr(table, "col_count", 0) or 0)
        cells = list(getattr(table, "cells", []) or [])
        cell_text_failed = False
        rows_list: list[tuple[str | None, ...]] = []
        for row_index, row in enumerate(extracted_rows):
            values: list[str | None] = []
            for column_index, cell_value in enumerate(row):
                fallback = None if cell_value is None else str(cell_value).strip()
                cell_index = row_index * column_count + column_index
                cell = (
                    cells[cell_index]
                    if column_count and cell_index < len(cells)
                    else None
                )
                if cell is not None:
                    try:
                        clipped_text = page.get_text(
                            "text", clip=fitz.Rect(cell)
                        ).strip()
                    except Exception as exc:
                        logger.warning(
                            "Table cell text extraction failed for document %s "
                            "page %s table %s row %s column %s: %s",
                            document_id,
                            page_number,
                            table_id,
                            row_index + 1,
                            column_index + 1,
                            exc,
                        )
                        cell_text_failed = True
                    else:
                        if clipped_text:
                            fallback = clipped_text
                values.append(fallback)
            rows_list.append(tuple(values))
        rows = tuple(rows_list)
        raw_headers = getattr(getattr(table, "header", None), "names", None)
        headers_list = [
            "" if value is None else str(value).strip()
            for value in (raw_headers or [])
        ]
        if column_count and rows and len(cells) >= column_count * len(rows):
            artifact_columns: set[int] = set()
            for column in range(column_count):
                widths = []
                empty = True
                for row_index, row in enumerate(rows):
                    if column < len(row) and row[column]:
                        empty = False
                    cell = cells[row_index * column_count + column]
                    if cell:
                        widths.append(float(cell[2]) - float(cell[0]))
                if empty and widths and max(widths) <= 3.0:
                    artifact_columns.add(column)
            if artifact_columns:
                rows = tuple(
                    tuple(
                        value for column, value in enumerate(row)
                        if column not in artifact_columns
                    )
                    for row in rows
                )
                headers_list = [
                    value for column, value in enumerate(headers_list)
                    if column not in artifact_columns
                ]
        headers = tuple(headers_list)
        has_values = any(cell for row in rows for cell in row)
        incomplete = (
            cell_text_failed
            or not rows
            or not has_values
            or not headers
            or any(not cell for row in rows for cell in row)
            or len({len(row) for row in rows}) > 1
        )
        review_reason = (
            "Text from one or more table cells could not be verified against "
            "the page; verify it against the PDF."
            if cell_text_failed
            else "The detected table has missing or inconsistent cells; "
            "verify it against the PDF."
            if incomplete
            else None
        )
        tables.append(
            ExtractedTable(
                document_id=document_id,
                filename=filename,
                page_number=page_number,
                table_id=table_id,
                headers=headers,
                rows=rows,
                status="review_required" if incomplete else "extracted",
                review_reason=review_reason,
            )
        )
    return tables
