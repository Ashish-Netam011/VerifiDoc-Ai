"""Vector store tests: exact cosine search, validation and persistence.

These use hand-built vectors so similarity outcomes are known exactly; no
embedding model is involved.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.vector_store import NumpyVectorStore, VectorStoreError

DIM = 4


def _vectors() -> np.ndarray:
    return np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.9, 0.1, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )


def _store(tmp_path, *, model: str = "test-model") -> NumpyVectorStore:
    return NumpyVectorStore(tmp_path / "vectors", DIM, model)


def _populate(store: NumpyVectorStore) -> list[str]:
    ids = ["c1", "c2", "c3", "c4"]
    metadata = [
        {"chunk_id": "c1", "document_id": "doc-a", "page_number": 1},
        {"chunk_id": "c2", "document_id": "doc-a", "page_number": 2},
        {"chunk_id": "c3", "document_id": "doc-b", "page_number": 1},
        {"chunk_id": "c4", "document_id": "doc-b", "page_number": 2},
    ]
    store.add(_vectors(), ids, metadata)
    return ids


def test_empty_index_returns_no_results(tmp_path) -> None:
    store = _store(tmp_path)
    assert len(store) == 0
    assert store.search(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)) == []


def test_add_and_top_k_search(tmp_path) -> None:
    store = _store(tmp_path)
    _populate(store)
    assert len(store) == 4

    results = store.search(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), top_k=2)
    assert [hit.chunk_id for hit in results] == ["c1", "c2"]
    assert results[0].score == pytest.approx(1.0, abs=1e-6)
    assert results[0].score >= results[1].score

    all_hits = store.search(
        np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), top_k=99
    )
    assert len(all_hits) == 4


def test_metadata_and_chunk_ids_preserved(tmp_path) -> None:
    store = _store(tmp_path)
    _populate(store)
    hits = store.search(np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32), top_k=1)
    assert hits[0].chunk_id == "c3"
    assert hits[0].metadata["document_id"] == "doc-b"
    assert hits[0].metadata["page_number"] == 1
    assert store.chunk_ids == ["c1", "c2", "c3", "c4"]


def test_vector_dimension_is_validated(tmp_path) -> None:
    store = _store(tmp_path)
    with pytest.raises(VectorStoreError, match="dimension mismatch"):
        store.add(np.ones((1, 3), dtype=np.float32), ["bad"])
    with pytest.raises(VectorStoreError, match="dimension mismatch"):
        store.add(np.ones((1, 5), dtype=np.float32), ["bad"])

    _populate(store)
    with pytest.raises(VectorStoreError, match="Query dimension mismatch"):
        store.search(np.ones(3, dtype=np.float32))


def test_zero_query_and_bad_top_k_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    _populate(store)
    with pytest.raises(VectorStoreError, match="must not be all zeros"):
        store.search(np.zeros(DIM, dtype=np.float32))
    with pytest.raises(ValueError):
        store.search(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), top_k=0)


def test_duplicate_chunk_ids_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    _populate(store)
    with pytest.raises(VectorStoreError, match="already exist"):
        store.add(np.ones((1, DIM), dtype=np.float32), ["c1"])


def test_persistence_roundtrip(tmp_path) -> None:
    store = _store(tmp_path)
    _populate(store)
    assert store.path.is_file()

    reloaded = _store(tmp_path)
    assert len(reloaded) == 4
    assert reloaded.chunk_ids == store.chunk_ids
    assert reloaded.metadata == store.metadata
    np.testing.assert_allclose(reloaded._matrix, store._matrix)

    hits = reloaded.search(np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32), top_k=1)
    assert hits[0].chunk_id == "c2"


def test_load_refuses_other_model(tmp_path) -> None:
    store = _store(tmp_path, model="model-one")
    _populate(store)
    other = NumpyVectorStore(
        tmp_path / "vectors", DIM, "model-two", autoload=False
    )
    with pytest.raises(VectorStoreError, match="built with model"):
        other.load()


def test_corrupted_index_is_reported(tmp_path) -> None:
    broken = NumpyVectorStore(tmp_path / "vectors", DIM, "test-model", autoload=False)
    broken.directory.mkdir(parents=True, exist_ok=True)
    broken.path.write_bytes(b"not an npz file")
    with pytest.raises(VectorStoreError, match="unreadable"):
        broken.load()


def test_remove_document_only_touches_that_document(tmp_path) -> None:
    store = _store(tmp_path)
    _populate(store)

    assert store.remove_document("doc-a") == 2
    assert store.chunk_ids == ["c3", "c4"]
    assert len(store) == 2

    store.save()
    reloaded = _store(tmp_path)
    assert reloaded.chunk_ids == ["c3", "c4"]
    assert all(item["document_id"] == "doc-b" for item in reloaded.metadata)
