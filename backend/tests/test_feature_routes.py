from pathlib import Path

import fitz
from fastapi.testclient import TestClient


def _pdf(path: Path, text: str) -> Path:
    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((40, 70), text, fontsize=11)
        document.save(path)
    finally:
        document.close()
    return path


def _upload(client: TestClient, path: Path) -> dict:
    with path.open("rb") as stream:
        response = client.post(
            "/api/documents/upload",
            files={"file": (path.name, stream, "application/pdf")},
        )
    assert response.status_code == 201, response.text
    return response.json()


def test_conflict_endpoint_returns_both_provenance_records(
    client: TestClient, tmp_path: Path
) -> None:
    _upload(
        client,
        _pdf(tmp_path / "lease-a.pdf", "Monthly rent is INR 15000 per month."),
    )
    _upload(
        client,
        _pdf(tmp_path / "lease-b.pdf", "Monthly rent is INR 18000 per month."),
    )

    response = client.post(
        "/api/conflicts",
        json={"query": "monthly rent amount", "top_k": 20},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    conflict = next(
        item for item in body["comparisons"]
        if item["status"] == "confirmed_conflict"
    )
    assert conflict["left"]["quotation"]
    assert conflict["right"]["quotation"]
    assert conflict["left"]["document_id"] != conflict["right"]["document_id"]
    assert conflict["left"]["page_number"] == conflict["right"]["page_number"] == 1


def test_amendment_endpoint_resolves_explicit_chain_for_as_of_date(
    client: TestClient, tmp_path: Path
) -> None:
    base = _upload(
        client,
        _pdf(tmp_path / "Base Agreement.pdf", "The base agreement terms apply."),
    )
    amendment = _upload(
        client,
        _pdf(
            tmp_path / "Amendment.pdf",
            "This amendment amends Base Agreement.pdf, clause 3 effective from "
            "2025-01-01.",
        ),
    )

    response = client.get("/api/amendments?as_of_date=2025-02-01")

    assert response.status_code == 200, response.text
    body = response.json()
    edge = next(
        item for item in body["amendments"]
        if item["amending_document_id"] == amendment["document_id"]
    )
    resolution = next(
        item for item in body["resolutions"]
        if item["document_id"] == base["document_id"]
    )
    assert edge["target_document_id"] == base["document_id"]
    assert edge["source"]["quotation"]
    assert resolution["applicable_document_id"] == amendment["document_id"]


def test_amendment_endpoint_rejects_invalid_as_of_date(client: TestClient) -> None:
    response = client.get("/api/amendments?as_of_date=not-a-date")

    assert response.status_code == 422
