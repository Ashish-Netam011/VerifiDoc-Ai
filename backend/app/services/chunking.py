"""Deterministic, page-aware character chunking.

Rules enforced here:

* a chunk never contains text from two different pages;
* ``start_offset`` / ``end_offset`` index into that page's extracted text, so
  the original text can be recovered exactly with ``text[start:end]``;
* whitespace-only windows are skipped, so no empty chunks are produced;
* ordering is page 1, then chunk 1..n, which makes output reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.pdf_service import ExtractedPage


class ChunkingError(ValueError):
    """Chunking parameters are invalid."""


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit of text from a single page."""

    chunk_id: str
    document_id: str
    page_number: int
    text: str
    start_offset: int
    end_offset: int

    def to_dict(self) -> dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "page_number": self.page_number,
            "text": self.text,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
        }


def _make_chunk_id(document_id: str, page_number: int, index: int) -> str:
    return f"{document_id}:p{page_number:04d}:c{index:04d}"


def chunk_page(
    document_id: str,
    page: ExtractedPage,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Chunk]:
    """Split one page's text into overlapping character windows."""
    if chunk_size <= 0:
        raise ChunkingError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ChunkingError("chunk_overlap must be >= 0 and smaller than chunk_size")

    text = page.text
    if not text.strip():
        return []

    step = chunk_size - chunk_overlap
    chunks: list[Chunk] = []
    start = 0
    index = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        window = text[start:end]
        if window.strip():
            chunks.append(
                Chunk(
                    chunk_id=_make_chunk_id(document_id, page.page_number, index),
                    document_id=document_id,
                    page_number=page.page_number,
                    text=window,
                    start_offset=start,
                    end_offset=end,
                )
            )
            index += 1
        if end >= len(text):
            break
        start += step  # always advances: step > 0

    return chunks


def chunk_pages(
    document_id: str,
    pages: tuple[ExtractedPage, ...] | list[ExtractedPage],
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Chunk]:
    """Chunk every page in order, keeping page boundaries intact."""
    chunks: list[Chunk] = []
    for page in pages:
        chunks.extend(
            chunk_page(
                document_id,
                page,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        )
    return chunks
