"""RAGAS-style offline metrics computed from this project's own components.

The four metric *definitions* follow the RAGAS evaluation suite. The *values*
are produced by this project's models — E5 embeddings, the NLI cross-encoder and
the configured LLM provider — not by the ``ragas`` package. Reports therefore
carry ``RAGAS_STYLE_NOTE`` and must never be presented as published RAGAS
scores or compared with them directly.

Metric shapes:

    faithfulness        supported claims / claims (runtime citation verdicts)
    answer_relevancy    mean cosine(original question, LLM-regenerated question)
    context_precision   rank-aware mean of precision@i at relevant positions
    context_recall     labeled facts entailed by at least one retrieved context

``answer_relevancy`` needs an LLM, so it is opt-in (``--ragas-style`` on
``python -m app.evaluation``); the other three reuse values the evaluator
already computes.
"""

from __future__ import annotations

import json
import re
from statistics import mean
from typing import Any, Sequence

import numpy as np

RAGAS_STYLE_NOTE = (
    "RAGAS-style metrics: the definitions follow the RAGAS suite, but the values "
    "are computed by this project's own E5, NLI and configured LLM components. "
    "They are not produced by the ragas package and are not comparable to "
    "published RAGAS scores."
)

QUESTION_SYSTEM_PROMPT = """You rewrite an answer into the questions it answers.
Return exactly one JSON object and nothing else, in this shape:
{"questions": [string, string, string]}
Each entry must be a standalone question answerable from the given answer alone.
Do not add commentary, markdown or extra keys."""

_QUESTION_WRAPPER_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_generated_questions(raw: str, limit: int) -> list[str]:
    """Parse the model's regeneration JSON; returns [] when unusable."""
    text = _QUESTION_WRAPPER_RE.sub("", str(raw or "").strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        payload = json.loads(text[start : end + 1])
    except ValueError:
        return []
    if not isinstance(payload, dict):
        return []
    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list):
        return []

    questions: list[str] = []
    seen: set[str] = set()
    for item in raw_questions:
        question = str(item or "").strip()
        if not question or question in seen:
            continue
        seen.add(question)
        questions.append(question)
        if len(questions) >= limit:
            break
    return questions


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors; 0.0 for a zero-length vector."""
    left = np.asarray(a, dtype=np.float32).reshape(-1)
    right = np.asarray(b, dtype=np.float32).reshape(-1)
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if not denominator:
        return 0.0
    return float(np.dot(left, right) / denominator)


async def answer_relevancy(
    question: str,
    answer: str,
    *,
    llm: Any,
    embedding_service: Any,
    num_questions: int = 3,
) -> dict[str, Any]:
    """RAGAS-style answer relevancy via LLM question regeneration.

    Returns ``{"score": None, "reason": ...}`` instead of raising, so an
    unavailable or unparseable model never turns an evaluation run into a crash
    or a fabricated score.
    """
    if not str(question).strip():
        raise ValueError("Answer relevancy needs a question.")
    if not str(answer).strip():
        return {
            "score": None,
            "generated_questions": [],
            "reason": "empty_answer",
        }

    prompt = (
        f"ANSWER:\n{answer}\n\n"
        f"Write {num_questions} different questions that this answer would answer."
    )
    try:
        raw = await llm.generate(
            prompt, system=QUESTION_SYSTEM_PROMPT, response_format="json"
        )
    except Exception as exc:  # noqa: BLE001 - recorded, never fatal
        return {
            "score": None,
            "generated_questions": [],
            "reason": f"llm_unavailable: {type(exc).__name__}",
        }

    questions = parse_generated_questions(raw, num_questions)
    if not questions:
        return {
            "score": None,
            "generated_questions": [],
            "reason": "unparseable_question_regeneration",
        }

    question_vector = embedding_service.embed_query(str(question).strip())
    question_vectors = embedding_service.embed_passages(questions)
    similarities = [
        cosine_similarity(question_vector, vector) for vector in question_vectors
    ]
    return {
        "score": mean(similarities),
        "generated_questions": questions,
        "per_question_similarity": similarities,
        "reason": None,
    }


def context_precision_ranked(relevance: Sequence[bool]) -> float | None:
    """Rank-aware context precision (RAGAS definition) for one query.

    The mean of ``precision@i`` over the positions holding a relevant context.
    Returns ``None`` when nothing retrieved is relevant, which RAGAS also treats
    as undefined rather than as a perfect or zero score.
    """
    if not relevance:
        return None
    precisions: list[float] = []
    seen = 0
    for index, is_relevant in enumerate(relevance, start=1):
        if not is_relevant:
            continue
        seen += 1
        precisions.append(seen / index)
    return mean(precisions) if precisions else None


def context_recall_from_facts(supported: Sequence[bool]) -> float | None:
    """Fraction of labeled facts found in the retrieved context."""
    flags = list(supported)
    if not flags:
        return None
    return sum(1 for flag in flags if flag) / len(flags)


def build_report(case_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Map evaluator case rows onto RAGAS-shaped metric names.

    Only documented mappings are reported; a metric whose inputs were absent
    stays ``None`` instead of silently becoming a number.
    """
    def average(key: str) -> float | None:
        values = [row[key] for row in case_rows if row.get(key) is not None]
        return mean(values) if values else None

    return {
        "faithfulness": average("faithfulness"),
        "answer_relevancy": average("answer_relevancy_generated"),
        "context_precision": average("context_precision_ranked"),
        "context_recall": average("context_recall_nli"),
        "instrumented": {
            "faithfulness": "Runtime citation verdicts (NLI).",
            "answer_relevancy": (
                "LLM question regeneration + E5 cosine; null unless "
                "--ragas-style ran with an available model."
            ),
            "context_precision": "Rank-aware, from NLI relevancy per context.",
            "context_recall": "Labeled facts entailed by retrieved contexts.",
        },
        "note": RAGAS_STYLE_NOTE,
    }
