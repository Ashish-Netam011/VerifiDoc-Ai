"""Hybrid retrieval tests: RRF maths, fusion behaviour and the search API."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import fitz
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.services.bm25_service import BM25Index, BM25Result, reset_bm25_index
from app.services.chunking import Chunk
from app.services.document_store import DocumentStore
from app.services.retrieval_service import (
    RetrievalService,
    reciprocal_rank_fusion,
    reset_retrieval_service,
)
from app.services.vector_store import SearchResult, reset_vector_stores

RRF_K = 60


# -- RRF maths --------------------------------------------------------------


def test_rrf_scores_follow_the_formula() -> None:
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "c"]], k=RRF_K)
    assert fused["a"] == pytest.approx(1 / (RRF_K + 1))
    # "b" is rank 2 in the first ranking and rank 1 in the second.
    assert fused["b"] == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 1))
    assert fused["c"] == pytest.approx(1 / (RRF_K + 2))


def test_rrf_deduplicates_within_one_ranking() -> None:
    fused = reciprocal_rank_fusion([["a", "a", "b"]], k=RRF_K)
    assert fused["a"] == pytest.approx(1 / (RRF_K + 1))
    assert fused["b"] == pytest.approx(1 / (RRF_K + 3))


def test_rrf_rejects_bad_constant() -> None:
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], k=0)


# -- service-level fusion ---------------------------------------------------


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

    def search(
        self, query: str, top_k: int = 6, *, document_id: str | None = None
    ) -> list[BM25Result]:
        hits = [
            hit
            for hit in self._hits
            if document_id is None
            or hit.metadata.get("document_id") == document_id
        ]
        return hits[:top_k]


def _seed_corpus(tmp_path: Path) -> DocumentStore:
    store = DocumentStore(tmp_path)
    for document_id, filename, chunks in (
        (
            "d1",
            "lease.pdf",
            [
                ("c1", 1, "The Tenant shall pay the monthly rent on the first day."),
                ("c2", 2, "3.2 Amendments require a written instrument."),
            ],
        ),
        ("d2", "addendum.pdf", [("c3", 1, "Notices must be delivered in writing.")]),
    ):
        store.add_document(
            {
                "document_id": document_id,
                "filename": filename,
                "file_path": f"pdfs/{document_id}/{filename}",
                "page_count": len(chunks),
                "uploaded_at": f"2026-01-01T00:00:0{document_id[-1]}.000000+00:00",
                "status": "processed",
                "chunk_count": len(chunks),
                "file_size_bytes": 1,
            }
        )
        store.write_chunks(
            document_id,
            [
                Chunk(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    page_number=page,
                    text=text,
                    start_offset=0,
                    end_offset=len(text),
                )
                for chunk_id, page, text in chunks
            ],
        )
    return store


def _search_result(
    chunk_id: str,
    score: float,
    document_id: str = "d1",
    filename: str = "lease.pdf",
) -> SearchResult:
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


def _bm25_result(chunk_id: str, score: float, document_id: str = "d1") -> BM25Result:
    return BM25Result(
        chunk_id=chunk_id,
        score=score,
        text="",
        metadata={"chunk_id": chunk_id, "document_id": document_id, "filename": "lease.pdf", "page_number": 2},
    )


def _service(
    tmp_path: Path,
    semantic: list[SearchResult],
    keyword: list[BM25Result],
    *,
    rrf_k: int = RRF_K,
) -> RetrievalService:
    return RetrievalService(
        tmp_path,
        embedding_service=StubEmbedding(),
        vector_store=StubVectorStore(semantic),
        bm25_index=StubBM25(keyword),
        rrf_k=rrf_k,
        default_top_k=5,
        document_store=_seed_corpus(tmp_path),
    )


def test_fusion_ranks_chunk_found_by_both_methods_first(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        semantic=[_search_result("c1", 0.91), _search_result("c2", 0.80)],
        keyword=[_bm25_result("c2", 4.2), _bm25_result("c3", 2.1)],
    )
    results = service.search("rent")
    assert [item.chunk_id for item in results] == ["c2", "c1", "c3"]
    assert results[0].rrf_score == pytest.approx(1 / (RRF_K + 1) + 1 / (RRF_K + 2))
    assert results[0].semantic_score == pytest.approx(0.80)
    assert results[0].bm25_score == pytest.approx(4.2)


def test_duplicate_chunks_appear_once_with_both_scores(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        semantic=[_search_result("c1", 0.9)],
        keyword=[_bm25_result("c1", 3.0)],
    )
    results = service.search("rent")
    assert len(results) == 1
    assert results[0].semantic_score is not None
    assert results[0].bm25_score is not None
    assert [item.chunk_id for item in results].count("c1") == 1


def test_keyword_only_results_keep_semantic_score_null(tmp_path: Path) -> None:
    service = _service(tmp_path, semantic=[], keyword=[_bm25_result("c1", 3.3)])
    results = service.search("3.2")
    assert len(results) == 1
    assert results[0].semantic_score is None
    assert results[0].bm25_score == pytest.approx(3.3)
    assert results[0].rrf_score == pytest.approx(1 / (RRF_K + 1))


def test_semantic_only_results_keep_bm25_score_null(tmp_path: Path) -> None:
    service = _service(tmp_path, semantic=[_search_result("c2", 0.77)], keyword=[])
    results = service.search("when is payment due")
    assert len(results) == 1
    assert results[0].bm25_score is None


def test_no_candidates_returns_empty_list(tmp_path: Path) -> None:
    service = _service(tmp_path, semantic=[], keyword=[])
    assert service.search("nothing matches") == []


def test_blank_query_and_bad_top_k(tmp_path: Path) -> None:
    service = _service(tmp_path, semantic=[], keyword=[])
    with pytest.raises(ValueError):
        service.search("   ")
    with pytest.raises(ValueError):
        service.search("rent", top_k=0)


def test_document_filter_applies_to_both_methods(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        semantic=[
            _search_result("c1", 0.9),
            _search_result("c3", 0.8, "d2", "addendum.pdf"),
        ],
        keyword=[_bm25_result("c1", 2.0), _bm25_result("c3", 1.0, "d2")],
    )
    results = service.search("writing", document_id="d2")
    assert [item.chunk_id for item in results] == ["c3"]
    assert results[0].filename == "addendum.pdf"


def test_result_text_and_page_are_hydrated_from_chunk_files(tmp_path: Path) -> None:
    service = _service(
        tmp_path,
        semantic=[_search_result("c2", 0.9)],
        keyword=[_bm25_result("c2", 1.5)],
    )
    result = service.search("amendments")[0]
    assert result.text == "3.2 Amendments require a written instrument."
    assert result.page_number == 1
    assert result.document_id == "d1"


def test_empty_corpus_returns_empty_list(tmp_path: Path) -> None:
    service = RetrievalService(
        tmp_path,
        embedding_service=StubEmbedding(),
        vector_store=StubVectorStore([]),
        bm25_index=BM25Index(),
        document_store=DocumentStore(tmp_path),
    )
    assert service.search("rent") == []


# -- API --------------------------------------------------------------------


def _write_pdf(path: Path, pages: list[str]) -> Path:
    document = fitz.open()
    try:
        for text in pages:
            page = document.new_page()
            y = 70
            for line in text.splitlines():
                for start in range(0, len(line), 90):
                    page.insert_text((45, y), line[start : start + 90], fontsize=9)
                    y += 13
        document.save(path)
    finally:
        document.close()
    return path


LEASE_PAGES = [
    "1. RENT\nThe Tenant shall pay the monthly rent of 1,200 EUR on the first day of each calendar month.",
    "3.2 Amendments\nThis agreement may be amended only by a written instrument signed by both parties.",
    "4. NOTICES\nAll notices must be delivered in writing to the address stated in Schedule A.",
]


@pytest.fixture()
def uploaded(client: TestClient, tmp_path: Path) -> dict:
    # A per-test marker keeps each upload distinguishable from the documents
    # earlier tests left in the shared test data directory.
    marker = f"mk{uuid4().hex[:8]}"
    pages = [f"DOCREF {marker}\n{page}" for page in LEASE_PAGES]
    pdf = _write_pdf(tmp_path / "lease.pdf", pages)
    with pdf.open("rb") as stream:
        response = client.post(
            "/api/documents/upload",
            files={"file": ("lease.pdf", stream, "application/pdf")},
        )
    assert response.status_code == 201, response.text
    return {**response.json(), "marker": marker}


def test_search_returns_exact_phrase_hit(client: TestClient, uploaded: dict) -> None:
    query = f"{uploaded['marker']} monthly rent of 1,200 EUR"
    response = client.post(
        "/api/search",
        json={
            "query": query,
            "top_k": 10,
            "document_id": uploaded["document_id"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["query"] == query
    assert body["result_count"] == len(body["results"]) >= 1

    rent_hits = [hit for hit in body["results"] if hit["page_number"] == 1]
    assert rent_hits, "the rent page must be retrieved"
    hit = rent_hits[0]
    assert hit["document_id"] == uploaded["document_id"]
    assert hit["filename"] == "lease.pdf"
    assert "monthly rent" in hit["text"]
    assert hit["bm25_score"] is not None
    assert hit["rrf_score"] > 0

    # BM25 must rank the rent page above the other pages of this document.
    best = max(
        (item["bm25_score"] for item in body["results"] if item["bm25_score"] is not None),
        default=None,
    )
    assert best == pytest.approx(hit["bm25_score"])


def test_search_by_clause_number(client: TestClient, uploaded: dict) -> None:
    body = client.post(
        "/api/search",
        json={
            "query": f"{uploaded['marker']} 3.2",
            "document_id": uploaded["document_id"],
        },
    ).json()
    assert body["result_count"] >= 1

    clause_hits = [hit for hit in body["results"] if hit["page_number"] == 2]
    assert clause_hits, "clause 3.2 lives on page 2"
    assert "3.2" in clause_hits[0]["text"]
    assert clause_hits[0]["chunk_id"].endswith("p0002:c0000")

    best = max(
        (item["bm25_score"] for item in body["results"] if item["bm25_score"] is not None),
        default=None,
    )
    assert best == pytest.approx(clause_hits[0]["bm25_score"])


def test_semantic_path_works_without_keyword_overlap(
    client: TestClient, uploaded: dict
) -> None:
    body = client.post(
        "/api/search", json={"query": "xylophone quokka zyzzyva"}
    ).json()
    assert body["result_count"] >= 1
    assert all(hit["bm25_score"] is None for hit in body["results"])
    assert all(hit["semantic_score"] is not None for hit in body["results"])


def test_document_filter_via_api(client: TestClient, uploaded: dict) -> None:
    body = client.post(
        "/api/search",
        json={
            "query": f"{uploaded['marker']} written",
            "document_id": uploaded["document_id"],
        },
    ).json()
    assert body["result_count"] >= 1
    assert {hit["document_id"] for hit in body["results"]} == {
        uploaded["document_id"]
    }

    missing = client.post(
        "/api/search", json={"query": "written", "document_id": "0" * 32}
    )
    assert missing.status_code == 404


def test_search_validation(client: TestClient) -> None:
    assert client.post("/api/search", json={"query": "   "}).status_code == 422
    assert client.post("/api/search", json={"query": "rent", "top_k": 0}).status_code == 422
    assert (
        client.post("/api/search", json={"query": "rent", "top_k": 51}).status_code
        == 422
    )
    assert (
        client.post("/api/search", json={"query": "rent", "document_id": "abc"}).status_code
        == 422
    )


def test_search_survives_restart(client: TestClient, uploaded: dict) -> None:
    """Dropping the in-memory indexes simulates a backend restart."""
    reset_bm25_index()
    reset_vector_stores()
    reset_retrieval_service()

    body = client.post(
        "/api/search",
        json={
            "query": f"{uploaded['marker']} written instrument",
            "document_id": uploaded["document_id"],
        },
    ).json()
    assert body["result_count"] >= 1
    assert {hit["document_id"] for hit in body["results"]} == {
        uploaded["document_id"]
    }
    pages = {hit["page_number"]: hit for hit in body["results"]}
    assert 2 in pages
    assert "written instrument" in pages[2]["text"]
    assert pages[2]["filename"] == "lease.pdf"
