"""BM25 keyword index over the stored document chunks.

The index is an in-memory structure built from the persisted chunk files
(``data/pdfs/<document_id>/chunks.json``) through :class:`DocumentStore`, so it
cannot drift from the text that was actually ingested. It is rebuilt lazily on
first use - including after a process restart - and updated incrementally when
a new document is ingested.

No extra file format is introduced for BM25: the chunk files stay the single
source of truth.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from rank_bm25 import BM25Okapi

from app.config import get_settings
from app.services.document_store import DocumentStore

logger = logging.getLogger(__name__)

DEFAULT_TOP_K = 6

# Tokenizer: words (with internal apostrophes) and numeric references such as
# "3", "3.2" or "4.1.2". Everything else - punctuation, currency symbols,
# section marks - is a separator. This keeps clause numbers searchable while
# making case and punctuation irrelevant.
_TOKEN_RE = re.compile(r"\d+(?:\.\d+)*|[a-z]+(?:'[a-z]+)?")


def tokenize(text: str) -> list[str]:
    """Lower-case token list that preserves numbers and clause references."""
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower())


@dataclass(frozen=True)
class BM25Result:
    """One keyword hit."""

    chunk_id: str
    score: float
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class BM25Index:
    """In-memory BM25 index keyed by chunk ID."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._tokens: dict[str, list[str]] = {}
        self._order: list[str] = []
        self._bm25: BM25Okapi | None = None
        self._dirty = True
        self._lock = threading.RLock()

    # -- construction --------------------------------------------------

    @property
    def chunk_ids(self) -> list[str]:
        with self._lock:
            return list(self._order)

    def __len__(self) -> int:
        with self._lock:
            return len(self._order)

    def add_records(self, records: Iterable[dict[str, Any]]) -> int:
        """Index chunk records; existing chunk IDs are skipped, never duplicated."""
        added = 0
        with self._lock:
            for record in records:
                chunk_id = str(record.get("chunk_id") or "").strip()
                if not chunk_id or chunk_id in self._records:
                    continue
                text = str(record.get("text") or "")
                self._records[chunk_id] = {
                    "chunk_id": chunk_id,
                    "document_id": str(record.get("document_id") or ""),
                    "filename": str(record.get("filename") or ""),
                    "page_number": int(record.get("page_number") or 0),
                    "text": text,
                }
                self._tokens[chunk_id] = tokenize(text)
                self._order.append(chunk_id)
                added += 1
            if added:
                self._dirty = True
        return added

    def load_from_store(self, store: DocumentStore) -> int:
        """Build the index from every chunk file referenced by the catalogue."""
        records: list[dict[str, Any]] = []
        for document in store.list_documents():
            document_id = str(document.get("document_id") or "")
            filename = str(document.get("filename") or "")
            for chunk in store.read_chunks(document_id):
                records.append(
                    {
                        "chunk_id": chunk.get("chunk_id"),
                        "document_id": document_id,
                        "filename": filename,
                        "page_number": chunk.get("page_number"),
                        "text": chunk.get("text"),
                    }
                )
        added = self.add_records(records)
        logger.info("BM25 index built from disk: %s chunks", added)
        return added

    def remove_document(self, document_id: str) -> int:
        with self._lock:
            keep = [
                chunk_id
                for chunk_id in self._order
                if self._records[chunk_id]["document_id"] != document_id
            ]
            removed = len(self._order) - len(keep)
            if removed:
                for chunk_id in set(self._order) - set(keep):
                    self._records.pop(chunk_id, None)
                    self._tokens.pop(chunk_id, None)
                self._order = keep
                self._dirty = True
        return removed

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._tokens.clear()
            self._order.clear()
            self._bm25 = None
            self._dirty = True

    # -- search --------------------------------------------------------

    def _ensure_bm25(self) -> BM25Okapi | None:
        with self._lock:
            if not self._order:
                return None
            if self._bm25 is None or self._dirty:
                corpus = [self._tokens[chunk_id] for chunk_id in self._order]
                if not any(corpus):
                    return None
                self._bm25 = BM25Okapi(corpus)
                self._dirty = False
            return self._bm25

    def search(
        self,
        query: str,
        top_k: int = DEFAULT_TOP_K,
        *,
        document_id: str | None = None,
    ) -> list[BM25Result]:
        """Rank chunks by BM25; chunks sharing no token with the query are excluded."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("BM25 query must not be empty.")
        if top_k <= 0:
            raise ValueError("top_k must be positive.")

        terms = tokenize(query)
        if not terms:
            return []

        with self._lock:
            bm25 = self._ensure_bm25()
            if bm25 is None:
                return []
            scores = bm25.get_scores(terms)
            query_terms = set(terms)
            candidates: list[tuple[float, str]] = []
            for position, chunk_id in enumerate(self._order):
                record = self._records[chunk_id]
                if document_id is not None and record["document_id"] != document_id:
                    continue
                if not query_terms.intersection(self._tokens[chunk_id]):
                    continue
                candidates.append((float(scores[position]), chunk_id))

        candidates.sort(key=lambda item: (-item[0], item[1]))
        results: list[BM25Result] = []
        for score, chunk_id in candidates[:top_k]:
            record = self._records[chunk_id]
            results.append(
                BM25Result(
                    chunk_id=chunk_id,
                    score=score,
                    text=record["text"],
                    metadata={
                        "chunk_id": chunk_id,
                        "document_id": record["document_id"],
                        "filename": record["filename"],
                        "page_number": record["page_number"],
                    },
                )
            )
        return results

    def get_text(self, chunk_id: str) -> str | None:
        with self._lock:
            record = self._records.get(chunk_id)
            return record["text"] if record else None


_index: BM25Index | None = None
_index_lock = threading.Lock()


def get_bm25_index() -> BM25Index:
    """Process-wide BM25 index, built from the persisted chunks on first use."""
    global _index
    if _index is None:
        with _index_lock:
            if _index is None:
                index = BM25Index()
                try:
                    index.load_from_store(DocumentStore(get_settings().data_dir))
                except Exception:  # noqa: BLE001 - degrade to empty, keep serving
                    logger.exception("Could not build the BM25 index from disk")
                _index = index
    return _index


def reset_bm25_index() -> None:
    """Drop the cached index so it is rebuilt from disk (used by tests/restart)."""
    global _index
    with _index_lock:
        _index = None


def rebuild_index_from_disk(index: BM25Index) -> int:
    """Reload ``index`` in place from persisted chunks."""
    index.clear()
    return index.load_from_store(DocumentStore(get_settings().data_dir))


__all__ = [
    "BM25Index",
    "BM25Result",
    "DEFAULT_TOP_K",
    "get_bm25_index",
    "rebuild_index_from_disk",
    "reset_bm25_index",
    "tokenize",
]
