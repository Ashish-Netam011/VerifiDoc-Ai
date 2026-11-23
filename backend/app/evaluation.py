"""Offline local RAG evaluation; never invoked by production request handlers."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

from app.config import get_settings
from app.services.embedding_service import get_embedding_service
from app.services.nli_service import get_nli_service
from app.services.qa_service import get_qa_service
from app.services.retrieval_service import RetrievalResult

VALID_DECISIONS = {"answer", "partial_answer", "abstain"}


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            case = json.loads(raw)
        except ValueError as exc:
            raise ValueError(f"Invalid JSON on line {line_number} of {path}.") from exc
        if (
            not isinstance(case, dict)
            or not case.get("id")
            or not case.get("question")
            or case.get("expected_decision") not in VALID_DECISIONS
            or not isinstance(case.get("required_facts", []), list)
        ):
            raise ValueError(f"Invalid evaluation case on line {line_number} of {path}.")
        cases.append(case)
    if not cases:
        raise ValueError(f"No evaluation cases found in {path}.")
    return cases


def score_case(
    case: dict[str, Any],
    result: Any,
    *,
    embedding_service: Any,
    nli_service: Any,
    entailment_threshold: float,
    contradiction_threshold: float,
) -> dict[str, Any]:
    """Score one QA result using local E5/NLI models and dataset labels."""
    required_facts = [str(fact) for fact in case.get("required_facts", [])]
    contexts: list[RetrievalResult] = list(result.retrieval)
    claims = list(result.claims)

    faithfulness = (
        sum(
            claim.verification is not None
            and claim.verification.status.value == "supported"
            for claim in claims
        )
        / len(claims)
        if claims
        else None
    )
    answer_relevance = None
    if result.answer.strip():
        query_vector = embedding_service.embed_query(str(case["question"]))
        answer_vector = embedding_service.embed_passages([result.answer])[0]
        denominator = float(np.linalg.norm(query_vector) * np.linalg.norm(answer_vector))
        if denominator:
            answer_relevance = float(np.dot(query_vector, answer_vector) / denominator)

    pairs = [
        (context.text, fact)
        for context in contexts
        for fact in required_facts
    ]
    scores = iter(nli_service.score_pairs(pairs)) if pairs else iter(())
    matrix = [
        [next(scores) for _ in required_facts]
        for _ in contexts
    ]

    context_precision = None
    context_recall = None
    if required_facts:
        relevant_contexts = sum(
            any(
                score.entailment >= entailment_threshold
                or score.contradiction >= contradiction_threshold
                for score in context_scores
            )
            for context_scores in matrix
        )
        context_precision = relevant_contexts / len(contexts) if contexts else 0.0
        supported_facts = sum(
            any(
                context_scores[fact_index].entailment >= entailment_threshold
                and context_scores[fact_index].contradiction
                < contradiction_threshold
                for context_scores in matrix
            )
            for fact_index in range(len(required_facts))
        )
        context_recall = supported_facts / len(required_facts)

    actual_decision = str(result.decision)
    return {
        "id": str(case["id"]),
        "category": str(case.get("category", "unspecified")),
        "expected_decision": str(case["expected_decision"]),
        "actual_decision": actual_decision,
        "decision_correct": actual_decision == case["expected_decision"],
        "faithfulness": faithfulness,
        "answer_relevance_e5_cosine": answer_relevance,
        "context_precision_nli": context_precision,
        "context_recall_nli": context_recall,
        "retrieved_context_count": len(contexts),
        "required_fact_count": len(required_facts),
    }


async def run_evaluation(
    cases: list[dict[str, Any]],
    *,
    qa_service: Any | None = None,
    embedding_service: Any | None = None,
    nli_service: Any | None = None,
    entailment_threshold: float | None = None,
    contradiction_threshold: float | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    qa_service = qa_service or get_qa_service()
    embedding_service = embedding_service or get_embedding_service()
    nli_service = nli_service or get_nli_service()
    entailment_threshold = (
        settings.nli_entailment_threshold
        if entailment_threshold is None
        else entailment_threshold
    )
    contradiction_threshold = (
        settings.nli_contradiction_threshold
        if contradiction_threshold is None
        else contradiction_threshold
    )

    case_results = []
    for case in cases:
        answer = await qa_service.answer(str(case["question"]))
        case_results.append(
            score_case(
                case,
                answer,
                embedding_service=embedding_service,
                nli_service=nli_service,
                entailment_threshold=entailment_threshold,
                contradiction_threshold=contradiction_threshold,
            )
        )

    def average(key: str) -> float | None:
        values = [row[key] for row in case_results if row[key] is not None]
        return mean(values) if values else None

    return {
        "case_count": len(case_results),
        "decision_accuracy": average("decision_correct"),
        "faithfulness": average("faithfulness"),
        "answer_relevance_e5_cosine": average("answer_relevance_e5_cosine"),
        "context_precision_nli": average("context_precision_nli"),
        "context_recall_nli": average("context_recall_nli"),
        "cases": case_results,
        "metric_notes": {
            "faithfulness": "Fraction of generated claims marked supported by runtime citation verification.",
            "answer_relevance_e5_cosine": "Cosine similarity proxy; not the canonical RAGAS answer-relevancy metric.",
            "context_precision_nli": "Retrieved contexts relevant to at least one labeled fact by entailment or contradiction threshold.",
            "context_recall_nli": "Labeled facts entailed by at least one retrieved context.",
            "all_scores": "Model scores are operating metrics, not calibrated probabilities or legal correctness.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default_dataset = Path(__file__).resolve().parents[1] / "evaluation" / "cases.jsonl"
    parser.add_argument("--dataset", type=Path, default=default_dataset)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = asyncio.run(run_evaluation(load_cases(args.dataset)))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
