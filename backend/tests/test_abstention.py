"""Abstention behaviour of ``POST /api/ask`` and of the QA service.

Ollama and the NLI verifier are replaced by deterministic stubs; the real
models are exercised outside the suite (see the Phase 3.3 report).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import fitz
import pytest
from fastapi.testclient import TestClient

from app.services.citation_verifier import (
    ClaimVerification,
    EvidenceAssessment,
    VerificationStatus,
)
from app.services.evidence_sufficiency import EvidenceSufficiencyEngine
from app.services.nli_service import NLIError
from app.services.qa_service import QAService
from app.services.retrieval_service import RetrievalResult, get_retrieval_service

LEASE_TEXT = (
    "The Tenant shall pay a monthly rent of INR 15,000, due on the fifth day of "
    "each calendar month. The Tenant shall pay a security deposit of INR 30,000. "
    "The Tenant shall not sublet the premises without the Landlord's prior "
    "written consent."
)

LEASE_PAGES = [
    "1. RENT\nThe Tenant shall pay a monthly rent of INR 15,000, due on the fifth day of each calendar month.",
    "2. DEPOSIT AND SUBLETTING\nThe Tenant shall pay a security deposit of INR 30,000. The Tenant shall "
    "not sublet the premises without the Landlord's prior written consent.",
]


# -- stubs ------------------------------------------------------------------


class StubOllama:
    model = "stub-qwen"

    def __init__(self, response: str = "", error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    async def generate(self, prompt, *, system=None, response_format=None):
        self.calls.append({"prompt": prompt, "system": system, "format": response_format})
        if self.error is not None:
            raise self.error
        return self.response


class StubRetrieval:
    def __init__(self, results: list[RetrievalResult]) -> None:
        self.results = results
        self.calls: list[dict] = []

    def search(self, query, *, top_k=6, document_id=None):
        self.calls.append({"query": query, "top_k": top_k, "document_id": document_id})
        return list(self.results)


class StatusVerifier:
    """Returns the given statuses in order, with a synthetic evidence assessment."""

    def __init__(self, statuses, chunk_id: str = "c1", contradiction: float = 0.97) -> None:
        self.statuses = list(statuses)
        self.chunk_id = chunk_id
        self.contradiction = contradiction
        self.calls = 0

    def verify_claims(self, claims, evidence):
        self.calls += 1
        verdicts = []
        for index, _ in enumerate(claims):
            status = self.statuses[min(index, len(self.statuses) - 1)]
            verdicts.append(
                ClaimVerification(
                    status=status,
                    reason="test",
                    entailment_score=0.97 if status is VerificationStatus.SUPPORTED else 0.01,
                    neutral_score=0.02,
                    contradiction_score=(
                        self.contradiction
                        if status is VerificationStatus.CONTRADICTED
                        else 0.01
                    ),
                    evidence=[
                        EvidenceAssessment(
                            chunk_id=self.chunk_id,
                            entailment=0.97
                            if status is VerificationStatus.SUPPORTED
                            else 0.01,
                            neutral=0.02,
                            contradiction=(
                                self.contradiction
                                if status is VerificationStatus.CONTRADICTED
                                else 0.01
                            ),
                            numeric_conflict=False,
                        )
                    ],
                )
            )
        return verdicts


class BrokenVerifier:
    def verify_claims(self, claims, evidence):
        raise NLIError("NLI model is not present in the local cache.")


def _result(
    text: str = LEASE_TEXT,
    *,
    chunk_id: str = "c1",
    document_id: str = "d1",
    filename: str = "lease.pdf",
    page: int = 1,
    semantic: float = 0.9,
) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        document_id=document_id,
        filename=filename,
        page_number=page,
        text=text,
        semantic_score=semantic,
        bm25_score=1.2,
        rrf_score=0.04,
    )


def _payload(answer: str, claims: list[dict]) -> str:
    return json.dumps({"answer": answer, "claims": claims, "limitations": []})


def _service(results, response, verifier) -> tuple[QAService, StubOllama]:
    ollama = StubOllama(response)
    return (
        QAService(
            StubRetrieval(results),
            ollama,
            verifier=verifier,
            sufficiency=EvidenceSufficiencyEngine(),
        ),
        ollama,
    )


def _run(service: QAService, question: str):
    return asyncio.run(service.answer(question))


# -- service-level behaviour ------------------------------------------------


def test_fully_supported_question_is_answered() -> None:
    service, _ = _service(
        [_result()],
        _payload(
            "The monthly rent is INR 15,000.",
            [{"text": "The monthly rent is INR 15,000.", "evidence_ids": ["E1"]}],
        ),
        StatusVerifier([VerificationStatus.SUPPORTED]),
    )
    result = _run(service, "What is the monthly rent?")
    assert result.decision == "answer"
    assert result.verification_status == "verified"
    assert result.missing_information == []
    assert result.evidence_gap_report["status"] == "answer"
    assert result.evidence_gap_report["supporting_evidence"][0]["chunk_id"] == "c1"


def test_empty_corpus_abstains_without_calling_the_model() -> None:
    service, ollama = _service([], "should not be called", StatusVerifier([]))
    result = _run(service, "What is the monthly rent?")
    assert ollama.calls == []
    assert result.decision == "abstain"
    assert result.claims == []
    assert "No relevant evidence" in result.answer
    assert result.evidence_gap_report["reason"] == "empty_corpus"


def test_irrelevant_evidence_abstains_before_generation() -> None:
    service, ollama = _service(
        [_result("Parking spaces are allocated by the Landlord.", semantic=0.22)],
        "should not be called",
        StatusVerifier([VerificationStatus.SUPPORTED]),
    )
    result = _run(service, "What is the monthly rent?")
    assert ollama.calls == []
    assert result.decision == "abstain"
    assert result.evidence_gap_report["reason"] == "no_relevant_evidence"


def test_high_similarity_without_entailment_abstains() -> None:
    service, ollama = _service(
        [_result("The Tenant shall keep the garden tidy.", semantic=0.93)],
        _payload(
            "The landlord's annual income is not stated.",
            [{"text": "The tenant keeps the garden tidy.", "evidence_ids": ["E1"]}],
        ),
        StatusVerifier([VerificationStatus.INSUFFICIENT]),
    )
    result = _run(service, "What is the landlord's annual income?")
    assert len(ollama.calls) == 1
    assert result.decision == "abstain"
    assert result.verification_status == "not_verified"


def test_two_part_question_with_one_supported_fact_is_partial() -> None:
    service, _ = _service(
        [_result()],
        _payload(
            "The monthly rent is INR 15,000 and the landlord earns INR 900,000.",
            [
                {"text": "The monthly rent is INR 15,000.", "evidence_ids": ["E1"]},
                {"text": "The landlord earns INR 900,000.", "evidence_ids": ["E1"]},
            ],
        ),
        StatusVerifier([VerificationStatus.SUPPORTED, VerificationStatus.INSUFFICIENT]),
    )
    result = _run(service, "What is the monthly rent and the landlord's annual income?")
    assert result.decision == "partial_answer"
    assert "INR 15,000" in result.answer
    assert "900,000" not in result.answer
    assert any("annual income" in item for item in result.missing_information)
    assert result.evidence_gap_report["status"] == "partial_answer"


def test_both_requested_facts_supported_is_an_answer() -> None:
    service, _ = _service(
        [_result()],
        _payload(
            "The monthly rent is INR 15,000 and the security deposit is INR 30,000.",
            [
                {"text": "The monthly rent is INR 15,000.", "evidence_ids": ["E1"]},
                {"text": "The security deposit is INR 30,000.", "evidence_ids": ["E1"]},
            ],
        ),
        StatusVerifier([VerificationStatus.SUPPORTED, VerificationStatus.SUPPORTED]),
    )
    result = _run(service, "What is the monthly rent and the security deposit?")
    assert result.decision == "answer"
    assert result.verification_status == "verified"


def test_missing_monetary_amount_abstains_with_gap_report() -> None:
    service, _ = _service(
        [_result()],
        _payload(
            "The documents do not specify the landlord's annual income.",
            [],
        ),
        StatusVerifier([]),
    )
    result = _run(service, "What is the landlord's annual income?")
    assert result.decision == "abstain"
    assert any("annual income" in item for item in result.missing_information)
    assert result.evidence_gap_report["coverage"]["components"][0]["status"] == "missing"


def test_wrong_amount_abstains_and_discloses_the_conflict() -> None:
    service, _ = _service(
        [_result()],
        _payload(
            "The monthly rent is INR 18,000.",
            [{"text": "The monthly rent is INR 18,000.", "evidence_ids": ["E1"]}],
        ),
        StatusVerifier([VerificationStatus.CONTRADICTED]),
    )
    result = _run(service, "What is the monthly rent?")
    assert result.decision == "abstain"
    assert result.verification_status == "contradicted"
    assert result.conflicts and result.conflicts[0]["chunk_id"] == "c1"
    assert "contradict" in result.answer.lower()


def test_conflicting_claims_abstain() -> None:
    service, _ = _service(
        [_result()],
        _payload(
            "The rent is INR 15,000 and also INR 18,000.",
            [
                {"text": "The monthly rent is INR 15,000.", "evidence_ids": ["E1"]},
                {"text": "The monthly rent is INR 18,000.", "evidence_ids": ["E1"]},
            ],
        ),
        StatusVerifier([VerificationStatus.SUPPORTED, VerificationStatus.CONTRADICTED]),
    )
    result = _run(service, "What is the monthly rent?")
    assert result.decision == "abstain"
    assert result.verification_status == "contradicted"
    assert result.evidence_gap_report["conflicts"]


def test_conditional_answer_is_kept_when_the_condition_is_preserved() -> None:
    service, _ = _service(
        [_result()],
        _payload(
            "The Tenant may sublet only with the Landlord's prior written consent.",
            [
                {
                    "text": "Subletting requires the Landlord's prior written consent.",
                    "evidence_ids": ["E1"],
                }
            ],
        ),
        StatusVerifier([VerificationStatus.SUPPORTED]),
    )
    result = _run(service, "Is subletting permitted?")
    assert result.decision == "answer"
    assert "prior written consent" in result.answer


def test_invalid_citation_is_never_answered() -> None:
    service, _ = _service(
        [_result()],
        _payload(
            "The monthly rent is INR 15,000.",
            [{"text": "The monthly rent is INR 15,000.", "evidence_ids": ["E1"]}],
        ),
        StatusVerifier([VerificationStatus.INVALID_CITATION]),
    )
    result = _run(service, "What is the monthly rent?")
    assert result.decision == "abstain"
    assert result.evidence_gap_report["reason"] == "invalid_citations"
    assert "INR 15,000" not in result.answer


def test_nli_unavailable_never_yields_a_verified_answer() -> None:
    service, _ = _service(
        [_result()],
        _payload(
            "The monthly rent is INR 15,000.",
            [{"text": "The monthly rent is INR 15,000.", "evidence_ids": ["E1"]}],
        ),
        BrokenVerifier(),
    )
    result = _run(service, "What is the monthly rent?")
    assert result.decision == "abstain"
    assert result.verification_status == "verification_unavailable"
    assert result.claims and result.claims[0].verification is None
    assert result.evidence_gap_report["reason"] == "verification_unavailable"
    assert "INR 15,000" not in result.answer


def test_all_neutral_claims_abstain() -> None:
    service, _ = _service(
        [_result()],
        _payload(
            "The monthly rent is INR 15,000.",
            [{"text": "The monthly rent is INR 15,000.", "evidence_ids": ["E1"]}],
        ),
        StatusVerifier([VerificationStatus.INSUFFICIENT]),
    )
    result = _run(service, "What is the monthly rent?")
    assert result.decision == "abstain"
    assert result.verification_status == "not_verified"


def test_mixed_claims_with_uncertain_coverage_are_separable() -> None:
    service, _ = _service(
        [_result()],
        _payload(
            "The rent is INR 15,000 and the garden is tidy.",
            [
                {"text": "The monthly rent is INR 15,000.", "evidence_ids": ["E1"]},
                {"text": "The garden is tidy.", "evidence_ids": ["E1"]},
            ],
        ),
        StatusVerifier([VerificationStatus.SUPPORTED, VerificationStatus.INSUFFICIENT]),
    )
    result = _run(service, "Summarise the payment terms.")
    assert result.decision == "partial_answer"
    assert "INR 15,000" in result.answer
    assert "garden" not in result.answer


def test_unsupported_claims_are_not_presented_as_answers() -> None:
    service, _ = _service(
        [_result()],
        _payload(
            "The monthly rent is INR 15,000.",
            [{"text": "The monthly rent is INR 15,000.", "evidence_ids": ["E1"]}],
        ),
        StatusVerifier([VerificationStatus.INSUFFICIENT]),
    )
    result = _run(service, "What is the monthly rent?")
    assert result.decision == "abstain"
    assert "INR 15,000" not in result.answer
    assert result.evidence_gap_report["status"] == "abstain"


# -- API behaviour ----------------------------------------------------------


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


def _upload(client: TestClient, tmp_path: Path, pages: list[str], name="lease.pdf"):
    marker = f"mk{uuid4().hex[:8]}"
    content = [f"DOCREF {marker}\n{page}" for page in pages]
    pdf = _write_pdf(tmp_path / name, content)
    with pdf.open("rb") as stream:
        response = client.post(
            "/api/documents/upload",
            files={"file": (name, stream, "application/pdf")},
        )
    assert response.status_code == 201, response.text
    return {**response.json(), "marker": marker}


def _patch_ollama(monkeypatch, stub: StubOllama) -> None:
    def factory() -> QAService:
        return QAService(
            get_retrieval_service(),
            stub,
            default_top_k=5,
            max_context_chars=6000,
        )

    monkeypatch.setattr("app.routers.qa.get_qa_service", factory)


def _patch_verifier(monkeypatch, verifier) -> None:
    monkeypatch.setattr(
        "app.services.qa_service.get_citation_verifier", lambda: verifier
    )


def test_api_reports_answer_with_gap_report(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploaded = _upload(client, tmp_path, LEASE_PAGES)
    _patch_ollama(
        monkeypatch,
        StubOllama(
            _payload(
                "The monthly rent is INR 15,000.",
                [{"text": "The monthly rent is INR 15,000.", "evidence_ids": ["E1"]}],
            )
        ),
    )
    _patch_verifier(monkeypatch, StatusVerifier([VerificationStatus.SUPPORTED]))

    body = client.post(
        "/api/ask",
        json={
            "question": f"{uploaded['marker']} what is the monthly rent?",
            "document_id": uploaded["document_id"],
        },
    ).json()

    assert body["decision"] == "answer"
    assert body["missing_information"] == []
    assert body["conflicts"] == []
    report = body["evidence_gap_report"]
    assert report["status"] == "answer"
    assert report["coverage"]["status"] == "identified"
    supporting = report["supporting_evidence"][0]
    chunks = client.get(f"/api/documents/{uploaded['document_id']}/chunks").json()[
        "chunks"
    ]
    assert supporting["chunk_id"] in {chunk["chunk_id"] for chunk in chunks}
    assert body["verification_status"] == "verified"


def test_api_partial_answer_hides_unsupported_claims(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploaded = _upload(client, tmp_path, LEASE_PAGES)
    _patch_ollama(
        monkeypatch,
        StubOllama(
            _payload(
                "The rent is INR 15,000 and the deposit is INR 30,000.",
                [
                    {"text": "The monthly rent is INR 15,000.", "evidence_ids": ["E1"]},
                    {"text": "The landlord earns INR 900,000.", "evidence_ids": ["E1"]},
                ],
            )
        ),
    )
    _patch_verifier(
        monkeypatch,
        StatusVerifier([VerificationStatus.SUPPORTED, VerificationStatus.INSUFFICIENT]),
    )

    body = client.post(
        "/api/ask",
        json={
            "question": (
                f"{uploaded['marker']} what is the monthly rent and the landlord's "
                "annual income?"
            ),
            "document_id": uploaded["document_id"],
        },
    ).json()

    assert body["decision"] == "partial_answer"
    assert "INR 15,000" in body["answer"]
    assert "900,000" not in body["answer"]
    assert body["missing_information"]
    assert body["retrieval"]["result_count"] >= 1
    # Claims stay visible with their verdicts, so nothing is hidden silently.
    assert [claim["verification"]["status"] for claim in body["claims"]] == [
        "supported",
        "insufficient",
    ]


def test_api_abstains_when_verification_is_unavailable(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploaded = _upload(client, tmp_path, LEASE_PAGES)
    _patch_ollama(
        monkeypatch,
        StubOllama(
            _payload(
                "The monthly rent is INR 15,000.",
                [{"text": "The monthly rent is INR 15,000.", "evidence_ids": ["E1"]}],
            )
        ),
    )
    _patch_verifier(monkeypatch, BrokenVerifier())

    body = client.post(
        "/api/ask",
        json={
            "question": f"{uploaded['marker']} what is the monthly rent?",
            "document_id": uploaded["document_id"],
        },
    ).json()

    assert body["decision"] == "abstain"
    assert body["verification_status"] == "verification_unavailable"
    assert body["claims"][0]["verification"] is None
    assert body["claims"][0]["sources"]
    assert "INR 15,000" not in body["answer"]


def test_api_keeps_the_phase_3_fields(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploaded = _upload(client, tmp_path, LEASE_PAGES)
    _patch_ollama(
        monkeypatch,
        StubOllama(
            _payload(
                "The monthly rent is INR 15,000.",
                [{"text": "The monthly rent is INR 15,000.", "evidence_ids": ["E1"]}],
            )
        ),
    )
    _patch_verifier(monkeypatch, StatusVerifier([VerificationStatus.SUPPORTED]))

    body = client.post(
        "/api/ask",
        json={"question": f"{uploaded['marker']} monthly rent"},
    ).json()

    for field in (
        "question",
        "answer",
        "claims",
        "limitations",
        "retrieval",
        "model",
        "verification_status",
        "decision",
        "missing_information",
        "conflicts",
        "evidence_gap_report",
    ):
        assert field in body, field
    assert body["claims"][0]["sources"]
    assert body["claims"][0]["verification"]["entailment_score"] == pytest.approx(0.97)
