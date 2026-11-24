"""Cross-document coverage: retrieval spread and multi-document answers."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest

from app.services.bm25_service import BM25Result
from app.services.chunking import Chunk
from app.services.document_store import DocumentStore
from app.services.qa_service import QAService
from app.services.retrieval_service import (
    RetrievalResult,
    RetrievalService,
    _apply_document_cap,
)
from app.services.vector_store import SearchResult


def _result(chunk_id: str, document_id: str, filename: str = "doc.pdf") -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        document_id=document_id,
        filename=filename,
        page_number=1,
        text=f"Text of {chunk_id}.",
        semantic_score=0.9,
        bm25_score=1.0,
        rrf_score=0.02,
    )


# -- the cap itself ---------------------------------------------------------


def test_cap_spreads_a_ranking_across_documents() -> None:
    ranked = [
        _result("a1", "d1"),
        _result("a2", "d1"),
        _result("a3", "d1"),
        _result("b1", "d2"),
        _result("c1", "d3"),
    ]

    capped = _apply_document_cap(ranked, 3, 1)

    assert [item.document_id for item in capped] == ["d1", "d2", "d3"]


def test_cap_tops_up_rather_than_returning_fewer_results() -> None:
    ranked = [_result("a1", "d1"), _result("a2", "d1"), _result("b1", "d2")]

    capped = _apply_document_cap(ranked, 3, 1)

    # The top-up keeps its original rank instead of jumping to the front.
    assert [item.chunk_id for item in capped] == ["a1", "a2", "b1"]


def test_cap_leaves_a_single_document_pool_untouched() -> None:
    ranked = [_result("a1", "d1"), _result("a2", "d1"), _result("a3", "d1")]

    assert [item.chunk_id for item in _apply_document_cap(ranked, 3, 1)] == [
        "a1",
        "a2",
        "a3",
    ]


def test_cap_can_be_disabled() -> None:
    ranked = [_result("a1", "d1"), _result("a2", "d1"), _result("b1", "d2")]

    assert [item.chunk_id for item in _apply_document_cap(ranked, 2, 0)] == [
        "a1",
        "a2",
    ]
    assert [item.chunk_id for item in _apply_document_cap(ranked, 2, None)] == [
        "a1",
        "a2",
    ]


# -- retrieval strategies ---------------------------------------------------


class StubEmbedding:
    def embed_query(self, text: str) -> np.ndarray:
        vector = np.ones(4, dtype=np.float32)
        return vector / np.linalg.norm(vector)


class StubVectorStore:
    def __init__(self, hits: list[SearchResult]) -> None:
        self._hits = hits

    def __len__(self) -> int:
        return len(self._hits)

    def search(self, query_vector, top_k: int = 6) -> list[SearchResult]:
        return list(self._hits)[:top_k]


class StubBM25:
    def __init__(self, hits: list[BM25Result]) -> None:
        self._hits = hits
        self.calls = 0

    def search(self, query: str, top_k: int = 6, *, document_id: str | None = None):
        self.calls += 1
        return list(self._hits)[:top_k]


def _seed(tmp_path: Path) -> DocumentStore:
    store = DocumentStore(tmp_path)
    for document_id, filename, texts in (
        ("d1", "lease.pdf", [("c1", "Rent is 1,450 EUR."), ("c2", "Rent is due monthly."), ("c3", "Rent reviews annually.")]),
        ("d2", "penalty.pdf", [("c4", "A late payment incurs 5%."), ("c5", "Penalties accrue daily.")]),
    ):
        store.add_document(
            {
                "document_id": document_id,
                "filename": filename,
                "file_path": f"pdfs/{document_id}/{filename}",
                "page_count": 1,
                "uploaded_at": "2026-01-01T00:00:00.000000+00:00",
                "status": "processed",
                "chunk_count": len(texts),
                "file_size_bytes": 1,
            }
        )
        store.write_chunks(
            document_id,
            [
                Chunk(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    page_number=1,
                    text=text,
                    start_offset=0,
                    end_offset=len(text),
                )
                for chunk_id, text in texts
            ],
        )
    return store


def _hit(chunk_id: str, document_id: str, score: float, filename: str) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        score=score,
        metadata={
            "chunk_id": chunk_id,
            "document_id": document_id,
            "filename": filename,
            "page_number": 1,
        },
    )


def _hybrid_service(tmp_path: Path, *, bm25: StubBM25 | None = None) -> RetrievalService:
    return RetrievalService(
        tmp_path,
        embedding_service=StubEmbedding(),
        vector_store=StubVectorStore(
            [
                _hit("c1", "d1", 0.95, "lease.pdf"),
                _hit("c2", "d1", 0.90, "lease.pdf"),
                _hit("c3", "d1", 0.85, "lease.pdf"),
                _hit("c4", "d2", 0.80, "penalty.pdf"),
            ]
        ),
        bm25_index=bm25 or StubBM25([]),
        document_store=_seed(tmp_path),
        default_top_k=4,
    )


def test_search_cap_spreads_results_over_documents(tmp_path: Path) -> None:
    service = _hybrid_service(tmp_path)

    results = service.search("rent payment penalty", top_k=3, max_per_document=1)

    assert [item.chunk_id for item in results] == ["c1", "c2", "c4"]
    # c2 is the top-up; c4 proves the second document reached the answer.
    assert {item.document_id for item in results} == {"d1", "d2"}


def test_search_without_the_cap_keeps_the_original_ranking(tmp_path: Path) -> None:
    service = _hybrid_service(tmp_path)

    results = service.search("rent payment penalty", top_k=2)

    assert [item.chunk_id for item in results] == ["c1", "c2"]


def test_keyword_only_strategy_skips_the_embedding_path(tmp_path: Path) -> None:
    bm25 = StubBM25(
        [
            BM25Result(
                chunk_id="c1",
                score=4.0,
                text="Rent is 1,450 EUR.",
                metadata={
                    "chunk_id": "c1",
                    "document_id": "d1",
                    "filename": "lease.pdf",
                    "page_number": 1,
                },
            )
        ]
    )
    service = _hybrid_service(tmp_path, bm25=bm25)

    results = service.search("rent", top_k=2, strategy="keyword")

    assert [item.chunk_id for item in results] == ["c1"]
    assert results[0].semantic_score is None
    assert bm25.calls == 1


def test_semantic_only_strategy_skips_bm25(tmp_path: Path) -> None:
    bm25 = StubBM25([])
    service = _hybrid_service(tmp_path, bm25=bm25)

    results = service.search("rent", top_k=2, strategy="semantic")

    assert [item.chunk_id for item in results] == ["c1", "c2"]
    assert results[0].bm25_score is None
    assert bm25.calls == 0


def test_unknown_strategy_is_rejected(tmp_path: Path) -> None:
    service = _hybrid_service(tmp_path)
    with pytest.raises(ValueError):
        service.search("rent", strategy="oracle")


# -- QA level ---------------------------------------------------------------


class StubLLM:
    model = "stub"

    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    async def generate(self, prompt, *, system=None, response_format=None):
        self.prompts.append(prompt)
        return self.payload


def test_answer_prompt_receives_evidence_from_more_than_one_document(
    tmp_path: Path,
) -> None:
    service = _hybrid_service(tmp_path)
    llm = StubLLM(
        json.dumps(
            {
                "answer": "Rent is 1,450 EUR and a late payment incurs 5%.",
                "claims": [
                    {"text": "Rent is 1,450 EUR.", "evidence_ids": ["E1"]},
                    {"text": "A late payment incurs 5%.", "evidence_ids": ["E3"]},
                ],
                "limitations": [],
            }
        )
    )
    qa = QAService(
        service,
        llm,
        default_top_k=3,
        max_chunks_per_document=1,
    )

    result = asyncio.run(qa.answer("rent and late payment"))

    prompt = llm.prompts[0]
    assert "lease.pdf" in prompt
    assert "penalty.pdf" in prompt
    assert {claim.sources[0].document_id for claim in result.claims} == {"d1", "d2"}


def test_document_scoped_question_is_not_capped_across_documents(
    tmp_path: Path,
) -> None:
    llm = StubLLM(
        json.dumps(
            {
                "answer": "Rent is 1,450 EUR.",
                "claims": [{"text": "Rent is 1,450 EUR.", "evidence_ids": ["E1"]}],
                "limitations": [],
            }
        )
    )
    qa = QAService(_hybrid_service(tmp_path), llm, default_top_k=3, max_chunks_per_document=1)

    asyncio.run(qa.answer("rent", document_id="d1"))

    prompt = llm.prompts[0]
    assert "lease.pdf" in prompt
    assert "penalty.pdf" not in prompt
