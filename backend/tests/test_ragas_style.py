"""RAGAS-style metric definitions and their conservative failure behaviour."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from app.ragas_style import (
    RAGAS_STYLE_NOTE,
    answer_relevancy,
    build_report,
    context_precision_ranked,
    context_recall_from_facts,
    cosine_similarity,
    parse_generated_questions,
)


class StubLLM:
    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.calls: list[dict] = []

    async def generate(self, prompt, *, system=None, response_format=None):
        self.calls.append({"prompt": prompt, "system": system})
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class StubEmbeddings:
    """One axis per question so cosines are predictable."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors
        self.model_name = "stub"

    def embed_query(self, text: str) -> np.ndarray:
        return np.array(self._vectors[text], dtype=np.float32)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return np.array([self._vectors[text] for text in texts], dtype=np.float32)


# -- parsing ----------------------------------------------------------------


def test_parse_generated_questions_accepts_fenced_json_and_dedupes() -> None:
    raw = '```json\n{"questions": ["Q1?", "Q1?", " Q2? ", ""]}\n```'
    assert parse_generated_questions(raw, 5) == ["Q1?", "Q2?"]


@pytest.mark.parametrize(
    "raw",
    ["", "not json", '{"items": ["a"]}', '["a"]', '{"questions": "a"}'],
)
def test_parse_generated_questions_rejects_unusable_payloads(raw: str) -> None:
    assert parse_generated_questions(raw, 3) == []


# -- metrics ----------------------------------------------------------------


def test_context_precision_ranked_matches_the_ragas_definition() -> None:
    # Relevant at positions 2 and 4 -> (1/2 + 2/4) / 2.
    assert context_precision_ranked([False, True, False, True]) == pytest.approx(0.5)
    assert context_precision_ranked([True, False]) == pytest.approx(1.0)
    assert context_precision_ranked([False, False]) is None
    assert context_precision_ranked([]) is None


def test_context_recall_from_facts() -> None:
    assert context_recall_from_facts([True, False]) == pytest.approx(0.5)
    assert context_recall_from_facts([]) is None


def test_cosine_similarity_handles_zero_vectors() -> None:
    assert cosine_similarity(np.array([1.0, 0.0]), np.array([1.0, 0.0])) == pytest.approx(1.0)
    assert cosine_similarity(np.array([0.0, 0.0]), np.array([1.0, 0.0])) == 0.0


def test_answer_relevancy_averages_regenerated_question_similarity() -> None:
    llm = StubLLM('{"questions": ["What is the rent?", "What rent applies?"]}')
    embeddings = StubEmbeddings(
        {
            "What is the rent?": [1.0, 0.0],
            "What rent applies?": [1.0, 0.0],
        }
    )

    result = asyncio.run(
        answer_relevancy(
            "What is the rent?",
            "The rent is INR 18,000.",
            llm=llm,
            embedding_service=embeddings,
        )
    )

    assert result["score"] == pytest.approx(1.0)
    assert result["reason"] is None
    assert result["per_question_similarity"] == pytest.approx([1.0, 1.0])
    assert llm.calls and "INR 18,000" in llm.calls[0]["prompt"]


def test_answer_relevancy_never_fabricates_a_score() -> None:
    answer = "The rent is INR 18,000."
    embeddings = StubEmbeddings({"q": [1.0, 0.0]})

    unavailable = asyncio.run(
        answer_relevancy(
            "q", answer, llm=StubLLM(RuntimeError("402")), embedding_service=embeddings
        )
    )
    assert unavailable["score"] is None
    assert unavailable["reason"].startswith("llm_unavailable")

    unparseable = asyncio.run(
        answer_relevancy(
            "q", answer, llm=StubLLM("no json here"), embedding_service=embeddings
        )
    )
    assert unparseable["score"] is None
    assert unparseable["reason"] == "unparseable_question_regeneration"

    empty = asyncio.run(
        answer_relevancy(
            "q", "   ", llm=StubLLM("{}"), embedding_service=embeddings
        )
    )
    assert empty["score"] is None
    assert empty["reason"] == "empty_answer"

    with pytest.raises(ValueError):
        asyncio.run(
            answer_relevancy(
                "  ", answer, llm=StubLLM("{}"), embedding_service=embeddings
            )
        )


# -- report -----------------------------------------------------------------


def test_build_report_labels_scores_as_ragas_style_and_keeps_nulls() -> None:
    report = build_report(
        [
            {
                "faithfulness": 1.0,
                "answer_relevancy_generated": None,
                "context_precision_ranked": 0.5,
                "context_recall_nli": 1.0,
            },
            {
                "faithfulness": 0.5,
                "answer_relevancy_generated": 0.8,
                "context_precision_ranked": None,
                "context_recall_nli": None,
            },
        ]
    )

    assert report["faithfulness"] == pytest.approx(0.75)
    assert report["answer_relevancy"] == pytest.approx(0.8)
    assert report["context_precision"] == pytest.approx(0.5)
    assert report["context_recall"] == pytest.approx(1.0)
    assert report["note"] == RAGAS_STYLE_NOTE
    assert "not produced by the ragas package" in report["note"]
