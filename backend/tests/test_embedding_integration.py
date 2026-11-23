"""Ingestion → embedding → vector index integration (fake embedding service)."""

from __future__ import annotations

from pathlib import Path

import fitz
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.services.embedding_service import EmbeddingModelError
from app.services.vector_store import get_vector_store


def _write_pdf(path: Path, pages: list[str], *, filename: str = "embedded.pdf") -> Path:
    target = path / filename
    document = fitz.open()
    try:
        for text in pages:
            page = document.new_page()
            page.insert_text((40, 60), text, fontsize=9)
            page.insert_text(
                (40, 80), "Clause content for the embedded document. " * 6, fontsize=8
            )
        document.save(target)
    finally:
        document.close()
    return target


def _upload(client: TestClient, pdf: Path):
    with pdf.open("rb") as stream:
        return client.post(
            "/api/documents/upload",
            files={"file": (pdf.name, stream, "application/pdf")},
        )


def test_upload_indexes_vectors(
    client: TestClient, tmp_path: Path, fake_embeddings
) -> None:
    pdf = _write_pdf(tmp_path, ["Page one about rent.", "Page two about notices."])
    response = _upload(client, pdf)
    assert response.status_code == 201, response.text
    body = response.json()
    document_id = body["document_id"]

    store = get_vector_store(
        get_settings().data_dir,
        model_name=fake_embeddings.model_name,
        dimension=fake_embeddings.expected_dimension,
    )
    indexed = [
        (chunk_id, meta)
        for chunk_id, meta in zip(store.chunk_ids, store.metadata)
        if meta.get("document_id") == document_id
    ]
    assert len(indexed) == body["chunk_count"]
    assert {meta["page_number"] for _, meta in indexed} == {1, 2}
    assert all(chunk_id.startswith(f"{document_id}:p") for chunk_id, _ in indexed)

    chunks = client.get(f"/api/documents/{document_id}/chunks").json()["chunks"]
    first = chunks[0]
    hits = store.search(fake_embeddings.embed_query(first["text"]), top_k=3)
    assert hits[0].chunk_id == first["chunk_id"]
    assert hits[0].metadata["page_number"] == first["page_number"]
    assert hits[0].metadata["filename"] == "embedded.pdf"
    assert hits[0].score == pytest.approx(1.0, abs=1e-5)


def test_vectors_survive_reload(tmp_path: Path, fake_embeddings) -> None:
    from app.services.vector_store import NumpyVectorStore

    directory = tmp_path / "vectors"
    store = NumpyVectorStore(directory, 384, fake_embeddings.model_name)
    store.add(
        np.eye(384, dtype=np.float32)[:2],
        ["v1", "v2"],
        [{"document_id": "d1"}, {"document_id": "d2"}],
    )
    reloaded = NumpyVectorStore(directory, 384, fake_embeddings.model_name)
    assert reloaded.chunk_ids == ["v1", "v2"]


def test_embedding_failure_discards_upload(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BrokenService:
        model_name = "broken-model"
        expected_dimension = 384

        async def aembed_passages(self, texts):
            raise EmbeddingModelError("Embedding model 'x' could not be loaded.")

        def embed_passages(self, texts):
            raise EmbeddingModelError("Embedding model 'x' could not be loaded.")

    monkeypatch.setattr(
        "app.routers.documents.get_embedding_service", lambda: BrokenService()
    )

    documents_before = client.get("/api/documents").json()["count"]
    pdf_dir = get_settings().data_dir / "pdfs"
    dirs_before = len([p for p in pdf_dir.iterdir() if p.is_dir()])

    response = _upload(client, _write_pdf(tmp_path, ["Should not be indexed."]))
    assert response.status_code == 503
    assert "could not be embedded" in response.json()["detail"]

    assert client.get("/api/documents").json()["count"] == documents_before
    assert len([p for p in pdf_dir.iterdir() if p.is_dir()]) == dirs_before
