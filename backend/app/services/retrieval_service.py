"""Hybrid retrieval: semantic search + BM25, fused with Reciprocal Rank Fusion.

RRF combines *ranks* rather than raw scores, so cosine similarity (roughly
0.6-0.95 for E5) and BM25 (unbounded, corpus-dependent) never have to be
rescaled against each other:

    rrf(chunk) = sum over methods of 1 / (k + rank),  k = 60 by default

Only ranks contribute; the original scores are kept for transparency and for
later citation scoring.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from app.config import get_settings
from app.services.bm25_service import BM25Index, BM25Result, get_bm25_index
from app.services.document_store import DocumentStore
from app.services.embedding_service import EmbeddingService, get_embedding_service
from app.services.vector_store import SearchResult, VectorStore, get_vector_store

logger = logging.getLogger(__name__)

DEFAULT_RRF_K = 60
DEFAULT_TOP_K = 6
# Each retriever contributes this many candidates before fusion, so a chunk
# ranked poorly by one method can still win after fusion.
CANDIDATE_MULTIPLIER = 4
MIN_CANDIDATES = 32


@dataclass(frozen=True)
class RetrievalResult:
    """A fused search hit with the evidence needed for later phases."""

    chunk_id: str
    document_id: str
    filename: str
    page_number: int
    text: str
    semantic_score: float | None
    bm25_score: float | None
    rrf_score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "filename": self.filename,
            "page_number": self.page_number,
            "text": self.text,
            "semantic_score": self.semantic_score,
            "bm25_score": self.bm25_score,
            "rrf_score": self.rrf_score,
        }


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], *, k: int = DEFAULT_RRF_K
) -> dict[str, float]:
    """Fuse ordered chunk-ID lists into ``{chunk_id: rrf_score}``.

    Ranks are 1-based. A chunk repeated inside one ranking only contributes at
    its best position.
    """
    if k < 1:
        raise ValueError("RRF constant k must be >= 1.")
    scores: dict[str, float] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for rank, chunk_id in enumerate(ranking, start=1):
            if not chunk_id or chunk_id in seen:
                continue
            seen.add(chunk_id)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


class RetrievalService:
    """Runs both retrievers over one corpus and fuses the rankings."""

    def __init__(
        self,
        data_dir: Path,
        *,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
        bm25_index: BM25Index,
        rrf_k: int = DEFAULT_RRF_K,
        default_top_k: int = DEFAULT_TOP_K,
        document_store: DocumentStore | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self._embedding = embedding_service
        self._vectors = vector_store
        self._bm25 = bm25_index
        self._rrf_k = rrf_k
        self._default_top_k = default_top_k
        self._documents = document_store or DocumentStore(self.data_dir)

    @property
    def rrf_k(self) -> int:
        return self._rrf_k

    # -- helpers -------------------------------------------------------

    def _candidate_depth(self, limit: int, *, filtered: bool) -> int:
        depth = max(limit * CANDIDATE_MULTIPLIER, MIN_CANDIDATES)
        if filtered:
            # With a document filter, over-fetch everything so the filter cannot
            # hide the only matching chunks.
            depth = max(depth, len(self._vectors))
        return depth

    def _hydrate(
        self, chunk_ids: Sequence[str], metadata: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Fetch chunk records (text, offsets) from the persisted chunk files."""
        by_document: dict[str, set[str]] = {}
        for chunk_id in chunk_ids:
            document_id = str(metadata.get(chunk_id, {}).get("document_id") or "")
            if document_id:
                by_document.setdefault(document_id, set()).add(chunk_id)

        hydrated: dict[str, dict[str, Any]] = {}
        for document_id, wanted in by_document.items():
            for chunk in self._documents.read_chunks(document_id):
                chunk_id = str(chunk.get("chunk_id") or "")
                if chunk_id in wanted:
                    hydrated[chunk_id] = chunk
        return hydrated

    # -- search --------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        document_id: str | None = None,
    ) -> list[RetrievalResult]:
        """Hybrid search; raises ``ValueError`` for a blank query."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Search query must not be empty.")
        query = query.strip()

        limit = top_k if top_k is not None else self._default_top_k
        if limit <= 0:
            raise ValueError("top_k must be positive.")
        depth = self._candidate_depth(limit, filtered=document_id is not None)

        # Semantic candidates (embedding errors propagate to the API layer).
        query_vector = self._embedding.embed_query(query)
        semantic_hits: list[SearchResult] = self._vectors.search(
            query_vector, top_k=max(depth, 1)
        )
        if document_id is not None:
            semantic_hits = [
                hit
                for hit in semantic_hits
                if str(hit.metadata.get("document_id") or "") == document_id
            ]
        semantic_hits = semantic_hits[:depth]

        # Keyword candidates.
        bm25_hits: list[BM25Result] = self._bm25.search(
            query, top_k=depth, document_id=document_id
        )

        semantic_by_id = {hit.chunk_id: hit for hit in semantic_hits}
        bm25_by_id = {hit.chunk_id: hit for hit in bm25_hits}

        fused = reciprocal_rank_fusion(
            [list(semantic_by_id), list(bm25_by_id)], k=self._rrf_k
        )
        if not fused:
            return []

        semantic_rank = {
            chunk_id: rank
            for rank, chunk_id in enumerate(semantic_by_id, start=1)
        }
        ordered = sorted(
            fused,
            key=lambda chunk_id: (
                -fused[chunk_id],
                semantic_rank.get(chunk_id, len(fused) + 1),
                chunk_id,
            ),
        )[:limit]

        metadata: dict[str, dict[str, Any]] = {}
        for chunk_id in ordered:
            hit = semantic_by_id.get(chunk_id)
            keyword = bm25_by_id.get(chunk_id)
            metadata[chunk_id] = dict(
                hit.metadata if hit is not None else keyword.metadata
            )
        chunks = self._hydrate(ordered, metadata)

        results: list[RetrievalResult] = []
        for chunk_id in ordered:
            hit = semantic_by_id.get(chunk_id)
            keyword = bm25_by_id.get(chunk_id)
            record = chunks.get(chunk_id, {})
            meta = metadata.get(chunk_id, {})

            text = str(record.get("text") or (keyword.text if keyword else "") or "")
            page_number = int(
                meta.get("page_number")
                or record.get("page_number")
                or 0
            )
            document = str(
                meta.get("document_id") or record.get("document_id") or ""
            )
            filename = str(meta.get("filename") or "")
            if not filename and document:
                catalogue = self._documents.get_document(document) or {}
                filename = str(catalogue.get("filename") or "")

            results.append(
                RetrievalResult(
                    chunk_id=chunk_id,
                    document_id=document,
                    filename=filename,
                    page_number=page_number,
                    text=text,
                    semantic_score=float(hit.score) if hit is not None else None,
                    bm25_score=float(keyword.score) if keyword is not None else None,
                    rrf_score=float(fused[chunk_id]),
                    metadata={
                        "start_offset": record.get("start_offset"),
                        "end_offset": record.get("end_offset"),
                    },
                )
            )
        return results


_service: RetrievalService | None = None
_service_lock = threading.Lock()


def get_retrieval_service() -> RetrievalService:
    """Process-wide retrieval service bound to the configured data directory."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                settings = get_settings()
                embedding = get_embedding_service()
                vectors = get_vector_store(
                    settings.data_dir,
                    model_name=embedding.model_name,
                    dimension=embedding.expected_dimension,
                )
                _service = RetrievalService(
                    settings.data_dir,
                    embedding_service=embedding,
                    vector_store=vectors,
                    bm25_index=get_bm25_index(),
                    rrf_k=settings.rrf_k,
                    default_top_k=settings.top_k,
                )
    return _service


def reset_retrieval_service() -> None:
    """Forget the cached service so a new configuration is picked up (tests)."""
    global _service
    with _service_lock:
        _service = None
