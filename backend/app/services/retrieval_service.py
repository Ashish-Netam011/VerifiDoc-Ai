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
from app.services.reranker_service import RerankerService, get_reranker_service
from app.services.vector_store import SearchResult, VectorStore, get_vector_store

logger = logging.getLogger(__name__)

DEFAULT_RRF_K = 60
DEFAULT_TOP_K = 6

# Retrieval ablations measured by the offline benchmark (app/benchmark.py).
# "hybrid_rerank" is the production path and the default; the others exist so
# each stage can be measured in isolation.
SEARCH_STRATEGIES = ("semantic", "keyword", "hybrid", "hybrid_rerank")
DEFAULT_STRATEGY = "hybrid_rerank"


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
    reranker_score: float | None = None
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
            "reranker_score": self.reranker_score,
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


def _apply_document_cap(
    results: Sequence[RetrievalResult],
    limit: int,
    max_per_document: int | None,
) -> list[RetrievalResult]:
    """Keep at most ``max_per_document`` hits per document, then top up.

    A single-document pool is returned unchanged: the cap exists so a question
    that spans several documents cannot be answered entirely from one of them.
    If the cap cannot fill ``limit``, the remaining slots come from the
    higher-ranked hits it skipped, so the caller never receives fewer results.
    """
    ranked = list(results)
    if max_per_document is None or max_per_document <= 0:
        return ranked[:limit]
    if len({result.document_id for result in ranked}) <= 1:
        return ranked[:limit]

    selected: list[RetrievalResult] = []
    overflow: list[RetrievalResult] = []
    per_document: dict[str, int] = {}
    for result in ranked:
        if len(selected) >= limit:
            break
        used = per_document.get(result.document_id, 0)
        if used < max_per_document:
            selected.append(result)
            per_document[result.document_id] = used + 1
        else:
            overflow.append(result)
    for result in overflow:
        if len(selected) >= limit:
            break
        selected.append(result)

    # Restore rank order: an overflow hit must not jump ahead of a better one.
    order = {result.chunk_id: rank for rank, result in enumerate(ranked)}
    return sorted(selected, key=lambda result: order[result.chunk_id])


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
        retrieval_candidate_k: int = 32,
        rerank_candidate_k: int = 32,
        reranker: RerankerService | None = None,
        document_store: DocumentStore | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self._embedding = embedding_service
        self._vectors = vector_store
        self._bm25 = bm25_index
        self._rrf_k = rrf_k
        self._default_top_k = default_top_k
        self._retrieval_candidate_k = retrieval_candidate_k
        self._rerank_candidate_k = rerank_candidate_k
        self._reranker = reranker
        self._documents = document_store or DocumentStore(self.data_dir)

    @property
    def rrf_k(self) -> int:
        return self._rrf_k

    # -- helpers -------------------------------------------------------

    def _candidate_depth(self, limit: int, *, filtered: bool) -> int:
        depth = max(limit, self._retrieval_candidate_k)
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
        strategy: str = DEFAULT_STRATEGY,
        max_per_document: int | None = None,
    ) -> list[RetrievalResult]:
        """Search one corpus; raises ``ValueError`` for a blank query.

        ``strategy`` selects which stages run, so the offline benchmark can
        measure each one: ``semantic`` (E5 only), ``keyword`` (BM25 only),
        ``hybrid`` (RRF fusion, no rerank) and ``hybrid_rerank`` (production).

        ``max_per_document`` spreads the results across documents so a question
        covering several documents is not answered from just one of them. It is
        a no-op when the candidate pool holds a single document.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Search query must not be empty.")
        query = query.strip()
        if strategy not in SEARCH_STRATEGIES:
            raise ValueError(
                f"strategy must be one of {', '.join(SEARCH_STRATEGIES)}"
            )

        limit = top_k if top_k is not None else self._default_top_k
        if limit <= 0:
            raise ValueError("top_k must be positive.")
        depth = self._candidate_depth(limit, filtered=document_id is not None)

        use_semantic = strategy in {"semantic", "hybrid", DEFAULT_STRATEGY}
        use_keyword = strategy in {"keyword", "hybrid", DEFAULT_STRATEGY}

        # Semantic candidates (embedding errors propagate to the API layer).
        semantic_hits: list[SearchResult] = []
        if use_semantic:
            query_vector = self._embedding.embed_query(query)
            semantic_hits = self._vectors.search(
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
        bm25_hits: list[BM25Result] = []
        if use_keyword:
            bm25_hits = self._bm25.search(
                query, top_k=depth, document_id=document_id
            )

        semantic_by_id = {hit.chunk_id: hit for hit in semantic_hits}
        bm25_by_id = {hit.chunk_id: hit for hit in bm25_hits}

        rankings: list[list[str]] = []
        if semantic_by_id:
            rankings.append(list(semantic_by_id))
        if bm25_by_id:
            rankings.append(list(bm25_by_id))
        fused = reciprocal_rank_fusion(rankings, k=self._rrf_k)
        if not fused:
            return []

        semantic_rank = {
            chunk_id: rank
            for rank, chunk_id in enumerate(semantic_by_id, start=1)
        }
        ordered_candidates = sorted(
            fused,
            key=lambda chunk_id: (
                -fused[chunk_id],
                semantic_rank.get(chunk_id, len(fused) + 1),
                chunk_id,
            ),
        )
        rerank = strategy == DEFAULT_STRATEGY and self._reranker is not None
        pool_size = max(limit, self._rerank_candidate_k) if rerank else limit
        if max_per_document is not None and max_per_document > 0:
            # The cap needs candidates to spread over; truncating to ``limit``
            # first would leave it nothing to draw a second document from.
            pool_size = max(pool_size, self._retrieval_candidate_k)
        ordered = ordered_candidates[:pool_size]

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
        if not rerank or not results:
            return _apply_document_cap(results, limit, max_per_document)

        reranker_scores = self._reranker.score(
            query, [result.text for result in results]
        )
        if len(reranker_scores) != len(results):
            raise ValueError(
                "The reranker returned a different number of scores than candidates."
            )
        reranked = [
            RetrievalResult(
                chunk_id=result.chunk_id,
                document_id=result.document_id,
                filename=result.filename,
                page_number=result.page_number,
                text=result.text,
                semantic_score=result.semantic_score,
                bm25_score=result.bm25_score,
                rrf_score=result.rrf_score,
                reranker_score=float(score),
                metadata=result.metadata,
            )
            for result, score in zip(results, reranker_scores)
        ]
        reranked.sort(
            key=lambda result: (
                -float(result.reranker_score or 0.0),
                -result.rrf_score,
                result.chunk_id,
            )
        )
        return _apply_document_cap(reranked, limit, max_per_document)


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
                    retrieval_candidate_k=settings.retrieval_candidate_k,
                    rerank_candidate_k=settings.rerank_candidate_k,
                    reranker=get_reranker_service(),
                )
    return _service


def reset_retrieval_service() -> None:
    """Forget the cached service so a new configuration is picked up (tests)."""
    global _service
    with _service_lock:
        _service = None
