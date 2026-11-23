"""Phase 2.1 tests: upload, page-aware extraction, chunking and the catalogue."""

from __future__ import annotations

import json
import os
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.services.pdf_service import extract_pdf

PAGE_ONE = "PAGE_ONE_MARKER " + " ".join(
    f"alpha{i:02d}" for i in range(1, 260)
)
PAGE_TWO = "PAGE_TWO_MARKER " + " ".join(
    f"beta{i:02d}" for i in range(1, 260)
)


def _write_pdf(path: Path, pages: list[str]) -> Path:
    """Build a PDF whose pages contain the given text (blank string = blank page)."""
    document = fitz.open()
    try:
        for text in pages:
            page = document.new_page()
            if text:
                y = 60.0
                for line in text.splitlines() or [text]:
                    for start in range(0, len(line), 90):
                        page.insert_text((40, y), line[start : start + 90], fontsize=8)
                        y += 11
        document.save(path)
    finally:
        document.close()
    return path


def _upload(client: TestClient, path: Path, name: str | None = None):
    with path.open("rb") as stream:
        return client.post(
            "/api/documents/upload",
            files={"file": (name or path.name, stream, "application/pdf")},
        )


# -- Task 1: upload ---------------------------------------------------------


def test_upload_valid_pdf_creates_metadata(client: TestClient, tmp_path: Path) -> None:
    path = _write_pdf(tmp_path / "report.pdf", [PAGE_ONE, PAGE_TWO])
    response = _upload(client, path)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["document_id"] and len(body["document_id"]) == 32
    assert body["filename"] == "report.pdf"
    assert body["page_count"] == 2
    assert body["status"] == "processed"
    assert body["chunk_count"] > 0
    assert body["file_path"].startswith("pdfs/")
    assert body["uploaded_at"].endswith("+00:00")

    stored = get_settings().data_dir / body["file_path"]
    assert stored.is_file()
    assert stored.stat().st_size == body["file_size_bytes"]


def test_reject_non_pdf_extension(client: TestClient, tmp_path: Path) -> None:
    path = _write_pdf(tmp_path / "real.pdf", ["hello"])
    response = _upload(client, path, name="notes.txt")
    assert response.status_code == 415
    assert "pdf" in response.json()["detail"].lower()


def test_reject_fake_pdf_signature(client: TestClient, tmp_path: Path) -> None:
    path = tmp_path / "fake.pdf"
    path.write_bytes(b"this is definitely not a pdf")
    response = _upload(client, path)
    assert response.status_code == 422
    assert "signature" in response.json()["detail"].lower()


def test_reject_empty_file(client: TestClient, tmp_path: Path) -> None:
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    response = _upload(client, path)
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_reject_pdf_without_text(client: TestClient, tmp_path: Path) -> None:
    path = _write_pdf(tmp_path / "blank.pdf", [""])
    response = _upload(client, path)
    assert response.status_code == 422
    assert "no extractable text" in response.json()["detail"].lower()


def test_reject_oversized_file(
    client: TestClient, tmp_path: Path, one_mb_limit: None
) -> None:
    path = tmp_path / "huge.pdf"
    path.write_bytes(b"%PDF-1.7\n" + os.urandom(1_500_000))
    response = _upload(client, path)
    assert response.status_code == 413
    assert "maximum upload size" in response.json()["detail"].lower()


def test_filename_traversal_is_neutralised(
    client: TestClient, tmp_path: Path
) -> None:
    path = _write_pdf(tmp_path / "trav.pdf", ["traversal content"])
    response = _upload(client, path, name="../../../evil.pdf")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["filename"] == "evil.pdf"
    assert body["file_path"].endswith("/evil.pdf")
    data_dir = get_settings().data_dir
    stored = (data_dir / body["file_path"]).resolve()
    assert data_dir.resolve() in stored.parents
    assert not (data_dir.parent / "evil.pdf").exists()
    assert not (data_dir.parent.parent / "evil.pdf").exists()


def test_duplicate_filenames_get_distinct_ids(
    client: TestClient, tmp_path: Path
) -> None:
    path = _write_pdf(tmp_path / "same.pdf", ["duplicate name test"])
    first = _upload(client, path)
    second = _upload(client, path)

    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["document_id"] != second.json()["document_id"]
    assert first.json()["file_path"] != second.json()["file_path"]

    data_dir = get_settings().data_dir
    assert (data_dir / first.json()["file_path"]).is_file()
    assert (data_dir / second.json()["file_path"]).is_file()

    listed = client.get("/api/documents").json()
    ids = {doc["document_id"] for doc in listed["documents"]}
    assert {first.json()["document_id"], second.json()["document_id"]} <= ids


# -- Task 2 + 3: extraction and chunking ------------------------------------


def test_page_numbers_preserved_and_no_cross_page_mixing(
    client: TestClient, tmp_path: Path
) -> None:
    path = _write_pdf(tmp_path / "pages.pdf", [PAGE_ONE, PAGE_TWO])
    document_id = _upload(client, path).json()["document_id"]

    body = client.get(f"/api/documents/{document_id}/chunks").json()
    assert body["page_count"] == 2
    assert body["chunk_count"] == len(body["chunks"])

    pages_seen = {chunk["page_number"] for chunk in body["chunks"]}
    assert pages_seen == {1, 2}

    for chunk in body["chunks"]:
        assert chunk["document_id"] == document_id
        assert chunk["text"].strip()

    page_one_text = "".join(
        chunk["text"] for chunk in body["chunks"] if chunk["page_number"] == 1
    )
    page_two_text = "".join(
        chunk["text"] for chunk in body["chunks"] if chunk["page_number"] == 2
    )
    assert page_one_text.startswith("PAGE_ONE_MARKER")
    assert page_two_text.startswith("PAGE_TWO_MARKER")
    assert "PAGE_TWO_MARKER" not in page_one_text
    assert "PAGE_ONE_MARKER" not in page_two_text
    assert "beta001" not in page_one_text
    assert "alpha001" not in page_two_text


def test_chunk_ordering_is_deterministic(client: TestClient, tmp_path: Path) -> None:
    path = _write_pdf(tmp_path / "order.pdf", [PAGE_ONE, PAGE_TWO])
    document_id = _upload(client, path).json()["document_id"]
    chunks = client.get(f"/api/documents/{document_id}/chunks").json()["chunks"]

    keys = [(chunk["page_number"], chunk["start_offset"]) for chunk in chunks]
    assert keys == sorted(keys)
    ids = [chunk["chunk_id"] for chunk in chunks]
    assert len(ids) == len(set(ids))

    repeat = client.get(f"/api/documents/{document_id}/chunks").json()["chunks"]
    assert repeat == chunks


def test_chunk_size_overlap_and_offsets(client: TestClient, tmp_path: Path) -> None:
    path = _write_pdf(tmp_path / "long.pdf", [PAGE_ONE])
    document_id = _upload(client, path).json()["document_id"]

    settings = get_settings()
    chunks = client.get(f"/api/documents/{document_id}/chunks").json()["chunks"]
    assert len(chunks) >= 3, "fixture page should produce several chunks"

    extracted = extract_pdf(
        settings.data_dir / f"pdfs/{document_id}/long.pdf", document_id, "long.pdf"
    )
    page_text = extracted.pages[0].text

    for chunk in chunks:
        assert chunk["end_offset"] - chunk["start_offset"] == len(chunk["text"])
        assert chunk["text"] == page_text[chunk["start_offset"] : chunk["end_offset"]]
        assert len(chunk["text"]) <= settings.chunk_size

    first, second = chunks[0], chunks[1]
    assert len(first["text"]) == settings.chunk_size
    assert second["start_offset"] == settings.chunk_size - settings.chunk_overlap
    assert first["text"][-settings.chunk_overlap :] == second["text"][
        : settings.chunk_overlap
    ]
    assert first["start_offset"] == 0


def test_blank_page_is_kept_but_produces_no_chunks(
    client: TestClient, tmp_path: Path
) -> None:
    path = _write_pdf(tmp_path / "mixed.pdf", [PAGE_ONE, ""])
    response = _upload(client, path)
    assert response.status_code == 201, response.text
    document_id = response.json()["document_id"]
    assert response.json()["page_count"] == 2

    extracted = extract_pdf(
        get_settings().data_dir / response.json()["file_path"], document_id, "mixed.pdf"
    )
    assert extracted.page_count == 2
    assert extracted.pages[1].page_number == 2
    assert extracted.pages[1].text.strip() == ""

    chunks = client.get(f"/api/documents/{document_id}/chunks").json()["chunks"]
    assert {chunk["page_number"] for chunk in chunks} == {1}


# -- Task 4 + 5: metadata and endpoints -------------------------------------


def test_metadata_is_persisted_to_disk(client: TestClient, tmp_path: Path) -> None:
    path = _write_pdf(tmp_path / "persist.pdf", [PAGE_ONE])
    created = _upload(client, path).json()

    index_file = get_settings().data_dir / "indexes" / "documents.json"
    assert index_file.is_file()
    payload = json.loads(index_file.read_text(encoding="utf-8"))
    records = {item["document_id"]: item for item in payload["documents"]}
    assert created["document_id"] in records

    record = records[created["document_id"]]
    assert record["filename"] == "persist.pdf"
    assert record["page_count"] == 1
    assert record["chunk_count"] == created["chunk_count"]
    assert record["status"] == "processed"
    assert record["file_path"] == created["file_path"]
    assert record["uploaded_at"]

    fetched = client.get(f"/api/documents/{created['document_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created


def test_list_documents_newest_first(client: TestClient, tmp_path: Path) -> None:
    older = _upload(client, _write_pdf(tmp_path / "a.pdf", ["first doc"])).json()
    newer = _upload(client, _write_pdf(tmp_path / "b.pdf", ["second doc"])).json()

    body = client.get("/api/documents").json()
    assert body["count"] == len(body["documents"])
    ids = [doc["document_id"] for doc in body["documents"]]
    assert ids.index(newer["document_id"]) <= ids.index(older["document_id"])


def test_unknown_document_returns_404(client: TestClient) -> None:
    missing = "0" * 32
    assert client.get(f"/api/documents/{missing}").status_code == 404
    assert client.get(f"/api/documents/{missing}/chunks").status_code == 404


def test_malformed_document_id_is_rejected(client: TestClient) -> None:
    response = client.get("/api/documents/..%2F..%2Fetc")
    assert response.status_code in (404, 422)


# -- Phase 1 regression ------------------------------------------------------


def test_phase1_endpoints_still_work(client: TestClient) -> None:
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["documents"] == "/api/documents"

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["backend"]["status"] == "ok"

    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    for expected in (
        "/api/health",
        "/api/test-llm",
        "/api/documents/upload",
        "/api/documents",
        "/api/documents/{document_id}",
        "/api/documents/{document_id}/chunks",
    ):
        assert expected in paths
