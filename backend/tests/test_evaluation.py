"""Offline RAG evaluation metrics are separate from request handling."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from app.evaluation import load_cases, score_case
from app.services.citation_verifier import VerificationStatus
from app.services.nli_service import NLIScores
from app.services.retrieval_service import RetrievalResult


class StubEmbeddingService:
    def embed_query(self, text: str) -> np.ndarray:
        return np.array([1.0, 0.0], dtype=np.float32)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return np.array([[0.8, 0.6] for _ in texts], dtype=np.float32)


class StubNLIService:
    def __init__(self, scores: list[NLIScores]) -> None:
        self.scores = scores

    def score_pairs(self, pairs):
        assert len(pairs) == len(self.scores)
        return self.scores


def _retrieval(chunk_id: str, text: str) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        document_id="doc",
        filename="fixture.pdf",
        page_number=1,
        text=text,
        semantic_score=0.8,
        bm25_score=1.0,
        rrf_score=0.02,
    )


def test_score_case_reports_separate_evidence_metrics() -> None:
    supported = SimpleNamespace(
        verification=SimpleNamespace(status=VerificationStatus.SUPPORTED)
    )
    result = SimpleNamespace(
        decision="answer",
        answer="The rent and due date are shown.",
        claims=[supported],
        retrieval=[_retrieval("c1", "Rent is stated."), _retrieval("c2", "Other terms.")],
    )
    entailment = NLIScores(0.9, 0.05, 0.05)
    neutral = NLIScores(0.05, 0.9, 0.05)

    metrics = score_case(
        {
            "id": "test",
            "category": "multi_evidence",
            "question": "What is the rent and due date?",
            "expected_decision": "answer",
            "required_facts": ["Rent is stated.", "Due date is stated."],
        },
        result,
        embedding_service=StubEmbeddingService(),
        nli_service=StubNLIService([entailment, neutral, neutral, neutral]),
        entailment_threshold=0.6,
        contradiction_threshold=0.6,
    )

    assert metrics["decision_correct"] is True
    assert metrics["faithfulness"] == 1
    assert metrics["answer_relevance_e5_cosine"] == pytest.approx(0.8)
    assert metrics["context_precision_nli"] == pytest.approx(0.5)
    assert metrics["context_recall_nli"] == pytest.approx(0.5)


def test_load_evaluation_dataset_validates_required_fields(tmp_path) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        '{"id":"case","question":"q","expected_decision":"abstain",'
        '"required_facts":[]}\n',
        encoding="utf-8",
    )

    cases = load_cases(dataset)

    assert cases[0]["id"] == "case"
    assert cases[0]["expected_decision"] == "abstain"
