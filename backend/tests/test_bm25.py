"""BM25 tests: tokenization, exact terms, clause numbers, filtering, rebuild."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.bm25_service import BM25Index, tokenize
from app.services.chunking import Chunk
from app.services.document_store import DocumentStore

CHUNKS = [
    {
        "chunk_id": "c1",
        "document_id": "d1",
        "filename": "lease.pdf",
        "page_number": 1,
        "text": "The Tenant shall pay the monthly rent of 1,200 EUR on the first day of each calendar month.",
    },
    {
        "chunk_id": "c2",
        "document_id": "d1",
        "filename": "lease.pdf",
        "page_number": 2,
        "text": "3.2 Amendments. This agreement may be amended only by a written instrument signed by both parties.",
    },
    {
        "chunk_id": "c3",
        "document_id": "d1",
        "filename": "lease.pdf",
        "page_number": 3,
        "text": "All notices must be delivered in writing to the address stated in Schedule A.",
    },
    {
        "chunk_id": "c4",
        "document_id": "d2",
        "filename": "addendum.pdf",
        "page_number": 1,
        "text": "The Landlord may increase the rent once per year by written notice to the Tenant.",
    },
    {
        "chunk_id": "c5",
        "document_id": "d2",
        "filename": "addendum.pdf",
        "page_number": 2,
        "text": "Either party may terminate this agreement with thirty days written notice.",
    },
]


@pytest.fixture()
def index() -> BM25Index:
    bm25 = BM25Index()
    bm25.add_records(CHUNKS)
    return bm25


def test_tokenizer_preserves_terms_numbers_and_clause_refs() -> None:
    assert tokenize("Section 3.2, § 4.1.2, 1,200 EUR.") == [
        "section",
        "3.2",
        "4.1.2",
        "1",
        "200",
        "eur",
    ]
    assert tokenize("") == []
    assert tokenize("RENT — Due!") == ["rent", "due"]


def test_exact_keyword_match(index: BM25Index) -> None:
    hits = index.search("monthly rent")
    assert hits
    assert hits[0].chunk_id == "c1"
    assert hits[0].metadata["page_number"] == 1
    assert hits[0].metadata["filename"] == "lease.pdf"


def test_clause_number_retrieval(index: BM25Index) -> None:
    hits = index.search("3.2")
    assert [hit.chunk_id for hit in hits] == ["c2"]

    section_hits = index.search("section 3.2")
    assert section_hits[0].chunk_id == "c2"


def test_duplicate_chunk_ids_are_ignored(index: BM25Index) -> None:
    before = len(index)
    index.add_records(CHUNKS)
    assert len(index) == before

    hits = index.search("rent")
    ids = [hit.chunk_id for hit in hits]
    assert len(ids) == len(set(ids))


def test_empty_query_and_empty_index() -> None:
    with pytest.raises(ValueError):
        BM25Index().search("   ")

    empty = BM25Index()
    assert len(empty) == 0
    assert empty.search("rent") == []


def test_queries_without_matching_terms_return_nothing(index: BM25Index) -> None:
    assert index.search("xylophone") == []


def test_document_filter(index: BM25Index) -> None:
    hits = index.search("written notice", document_id="d2")
    assert hits
    assert {hit.metadata["document_id"] for hit in hits} == {"d2"}

    assert index.search("rent", document_id="does-not-exist") == []


def test_remove_document_is_scoped(index: BM25Index) -> None:
    assert index.remove_document("d1") == 3
    assert len(index) == 2
    assert index.search("3.2") == []
    assert {hit.metadata["document_id"] for hit in index.search("rent")} == {"d2"}


def test_rebuild_from_persisted_chunks(tmp_path: Path) -> None:
    store = DocumentStore(tmp_path)
    store.add_document(
        {
            "document_id": "d1",
            "filename": "lease.pdf",
            "file_path": "pdfs/d1/lease.pdf",
            "page_count": 2,
            "uploaded_at": "2026-01-01T00:00:00.000000+00:00",
            "status": "processed",
            "chunk_count": 2,
            "file_size_bytes": 10,
        }
    )
    store.write_chunks(
        "d1",
        [
            Chunk(
                chunk_id="c1",
                document_id="d1",
                page_number=1,
                text=CHUNKS[0]["text"],
                start_offset=0,
                end_offset=len(CHUNKS[0]["text"]),
            ),
            Chunk(
                chunk_id="c2",
                document_id="d1",
                page_number=2,
                text=CHUNKS[1]["text"],
                start_offset=0,
                end_offset=len(CHUNKS[1]["text"]),
            ),
        ],
    )

    rebuilt = BM25Index()
    added = rebuilt.load_from_store(store)
    assert added == 2
    assert rebuilt.get_text("c2").startswith("3.2 Amendments")
    assert rebuilt.search("written instrument")[0].chunk_id == "c2"
    assert rebuilt.search("written instrument")[0].metadata["filename"] == "lease.pdf"
