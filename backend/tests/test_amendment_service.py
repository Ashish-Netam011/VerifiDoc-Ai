from datetime import date

from app.services.amendment_service import build_amendment_report


def _doc(document_id: str, filename: str) -> dict[str, str]:
    return {"document_id": document_id, "filename": filename}


def _chunk(document_id: str, text: str, page: int = 1) -> dict[str, object]:
    return {
        "document_id": document_id,
        "filename": f"{document_id}.pdf",
        "page_number": page,
        "chunk_id": f"{document_id}:p0001:c0001",
        "text": text,
    }


def _chain():
    documents = [
        _doc("a", "Base Agreement.pdf"),
        _doc("b", "First Amendment.pdf"),
        _doc("c", "Second Amendment.pdf"),
    ]
    chunks = {
        "b": [
            _chunk(
                "b",
                "This amendment amends Base Agreement.pdf, clause 3, effective "
                "from 2025-01-01. Amendment dated 2024-12-01.",
            )
        ],
        "c": [
            _chunk(
                "c",
                "This amendment amends First Amendment.pdf, clause 3, effective "
                "from 2025-06-01. Amendment dated 2025-05-01.",
            )
        ],
    }
    return documents, chunks


def test_single_amendment_resolves_with_source_evidence() -> None:
    documents, chunks = _chain()
    report = build_amendment_report(
        documents[:2], {"b": chunks["b"]}, as_of_date=date(2025, 2, 1)
    )

    edge = report["amendments"][0]
    resolution = report["resolutions"][0]
    assert edge["target_document_id"] == "a"
    assert edge["effective_date"] == "2025-01-01"
    assert edge["amendment_date"] == "2024-12-01"
    assert edge["affected_clause"] == "3"
    assert edge["source"]["page_number"] == 1
    assert "Base Agreement.pdf" in edge["source"]["quotation"]
    assert resolution["applicable_document_id"] == "b"
    assert resolution["document_filename"] == "Base Agreement.pdf"
    assert resolution["applicable_filename"] == "First Amendment.pdf"


def test_multi_document_chain_resolves_as_of_requested_date() -> None:
    documents, chunks = _chain()
    report = build_amendment_report(
        documents, chunks, as_of_date=date(2025, 7, 1)
    )

    root = next(item for item in report["resolutions"] if item["document_id"] == "a")
    assert root["chain"] == ["a", "b", "c"]
    assert root["chain_filenames"] == [
        "Base Agreement.pdf",
        "First Amendment.pdf",
        "Second Amendment.pdf",
    ]
    assert root["applicable_document_id"] == "c"


def test_future_amendment_does_not_apply_before_its_effective_date() -> None:
    documents, chunks = _chain()
    report = build_amendment_report(
        documents, chunks, as_of_date=date(2024, 12, 31)
    )

    root = next(item for item in report["resolutions"] if item["document_id"] == "a")
    assert root["status"] == "no_amendment"
    assert root["applicable_document_id"] == "a"


def test_later_effective_amendment_supersedes_earlier_version_as_of_date() -> None:
    documents, chunks = _chain()
    before = build_amendment_report(documents, chunks, as_of_date=date(2025, 3, 1))
    after = build_amendment_report(documents, chunks, as_of_date=date(2025, 7, 1))

    before_root = next(item for item in before["resolutions"] if item["document_id"] == "a")
    after_root = next(item for item in after["resolutions"] if item["document_id"] == "a")
    assert before_root["applicable_document_id"] == "b"
    assert after_root["applicable_document_id"] == "c"


def test_missing_target_is_explicit() -> None:
    documents = [_doc("b", "Amendment.pdf")]
    chunks = {"b": [_chunk("b", "This amendment amends Prior Agreement, clause 2.")]}

    report = build_amendment_report(documents, chunks)
    edge = report["amendments"][0]

    assert edge["target_document_id"] is None
    assert edge["status"] == "missing_target"
    assert edge["target_reference"] == "Prior Agreement"
    assert edge in report["chain_issues"]


def test_schema_descriptions_are_not_treated_as_legal_amendments() -> None:
    documents = [_doc("a", "Architecture.pdf")]
    chunks = {
        "a": [
            _chunk(
                "a",
                "documents 1 --- 0..1 amends (amends_id links an amendment to its target)",
            )
        ]
    }

    report = build_amendment_report(documents, chunks)

    assert report["amendments"] == []
    assert report["chain_issues"] == []


def test_ambiguous_effective_date_abstains_from_resolution() -> None:
    documents = [_doc("a", "Base.pdf"), _doc("b", "Amendment.pdf")]
    chunks = {
        "b": [
            _chunk(
                "b",
                "This amendment amends Base.pdf, effective from 01/02/2025.",
            )
        ]
    }

    report = build_amendment_report(
        documents, chunks, as_of_date=date(2025, 3, 1)
    )
    edge = report["amendments"][0]
    resolution = report["resolutions"][0]
    assert edge["effective_date"] is None
    assert edge["effective_date_ambiguous"] is True
    assert resolution["status"] == "ambiguous_effective_date"
    assert resolution["applicable_document_id"] is None


def test_circular_relationship_is_reported() -> None:
    documents = [_doc("a", "Document A.pdf"), _doc("b", "Document B.pdf")]
    chunks = {
        "a": [_chunk("a", "This amendment amends Document B.pdf effective from 2025-01-01.")],
        "b": [_chunk("b", "This amendment amends Document A.pdf effective from 2025-02-01.")],
    }

    report = build_amendment_report(
        documents, chunks, as_of_date=date(2025, 3, 1)
    )

    assert all(edge["status"] == "circular_relationship" for edge in report["amendments"])
    assert any(item["status"] == "circular_relationship" for item in report["resolutions"])


def test_no_amendment_returns_original_document() -> None:
    documents = [_doc("a", "Agreement.pdf")]

    report = build_amendment_report(
        documents, {"a": [_chunk("a", "The agreement establishes the rules.")]},
        as_of_date=date(2025, 1, 1),
    )

    assert report["amendments"] == []
    resolutions = report["resolutions"]
    assert len(resolutions) == 1
    assert resolutions[0]["document_id"] == "a"
    assert resolutions[0]["applicable_document_id"] == "a"
    assert resolutions[0]["status"] == "no_amendment"
    assert resolutions[0]["chain"] == ["a"]
    assert resolutions[0]["document_filename"] == "Agreement.pdf"
    assert resolutions[0]["applicable_filename"] == "Agreement.pdf"
    assert resolutions[0]["chain_filenames"] == ["Agreement.pdf"]
    assert resolutions[0]["superseded_clauses"] == {}
    assert resolutions[0]["reason"] == "No applicable amendment found for this document."
