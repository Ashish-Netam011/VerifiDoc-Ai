"""Offline retrieval benchmark; never invoked by production request handlers.

The Q&A evaluator (``app.evaluation``) measures end-to-end answer quality. This
module measures retrieval on its own, which is the only way to tell whether a
change helped the ranking stage or merely changed the generation stage.

It reports binary-relevance retrieval metrics over hand-labeled qrels:

    recall@k     relevant chunks found in the top k / relevant chunks
    precision@k  relevant chunks found in the top k / k
    MRR          1 / rank of the first relevant chunk (0 when none is returned)
    nDCG@k       DCG@k / ideal DCG@k, binary gains

Each retrieval stage is measured separately (``semantic``, ``keyword``,
``hybrid``, ``hybrid_rerank``) so the contribution of BM25 fusion and of the
cross-encoder reranker is visible instead of assumed.

The qrels are a small, single-annotator label set for the local demo corpus. The
numbers are a regression baseline for that corpus, not a benchmark of the
retrieval method in general.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Sequence

from app.services.retrieval_service import (
    DEFAULT_STRATEGY,
    SEARCH_STRATEGIES,
    RetrievalResult,
)

DEFAULT_KS = (1, 3, 5, 10)


# -- metrics ----------------------------------------------------------------


def recall_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Fraction of the labeled relevant chunks present in the top ``k``."""
    relevant_set = set(relevant)
    if not relevant_set:
        raise ValueError("recall_at_k needs at least one relevant chunk id.")
    if k <= 0:
        raise ValueError("k must be positive.")
    return len(relevant_set.intersection(ranked[:k])) / len(relevant_set)


def precision_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Fraction of the top ``k`` that is relevant (denominator is ``k``)."""
    relevant_set = set(relevant)
    if k <= 0:
        raise ValueError("k must be positive.")
    return len(relevant_set.intersection(ranked[:k])) / k


def reciprocal_rank(ranked: Sequence[str], relevant: Iterable[str]) -> float:
    """``1 / rank`` of the first relevant chunk, or ``0.0`` when none appear."""
    relevant_set = set(relevant)
    for rank, chunk_id in enumerate(ranked, start=1):
        if chunk_id in relevant_set:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(
    ranked: Sequence[str], relevant: Iterable[str], k: int = 10
) -> float:
    """Normalised discounted cumulative gain with binary gains."""
    relevant_set = set(relevant)
    if not relevant_set:
        raise ValueError("ndcg_at_k needs at least one relevant chunk id.")
    if k <= 0:
        raise ValueError("k must be positive.")

    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, chunk_id in enumerate(ranked[:k], start=1)
        if chunk_id in relevant_set
    )
    ideal = sum(
        1.0 / math.log2(rank + 1)
        for rank in range(1, min(k, len(relevant_set)) + 1)
    )
    return dcg / ideal if ideal else 0.0


# -- dataset ----------------------------------------------------------------


@dataclass(frozen=True)
class Qrel:
    """One labeled question: the chunks that genuinely contain its answer."""

    id: str
    question: str
    relevant_chunk_ids: tuple[str, ...]
    document_id: str | None = None
    category: str = "unspecified"


def load_qrels(path: Path) -> list[Qrel]:
    """Read and validate a JSONL qrels file; raises ``ValueError``."""
    qrels: list[Qrel] = []
    for line_number, raw in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except ValueError as exc:
            raise ValueError(f"Invalid JSON on line {line_number} of {path}.") from exc
        if not isinstance(entry, dict):
            raise ValueError(f"Line {line_number} of {path} is not an object.")

        identifier = str(entry.get("id") or "").strip()
        question = str(entry.get("question") or "").strip()
        relevant = entry.get("relevant_chunk_ids")
        document_id = entry.get("document_id")

        if not identifier or not question:
            raise ValueError(
                f"Line {line_number} of {path} needs 'id' and 'question'."
            )
        if not isinstance(relevant, list) or not relevant:
            raise ValueError(
                f"Line {line_number} of {path} needs a non-empty "
                "'relevant_chunk_ids' list."
            )
        chunk_ids = tuple(
            dict.fromkeys(str(item).strip() for item in relevant if str(item).strip())
        )
        if not chunk_ids:
            raise ValueError(
                f"Line {line_number} of {path} has no usable 'relevant_chunk_ids'."
            )
        if document_id is not None and not str(document_id).strip():
            raise ValueError(
                f"Line {line_number} of {path} has an empty 'document_id'."
            )

        qrels.append(
            Qrel(
                id=identifier,
                question=question,
                relevant_chunk_ids=chunk_ids,
                document_id=str(document_id) if document_id is not None else None,
                category=str(entry.get("category") or "unspecified"),
            )
        )
    if not qrels:
        raise ValueError(f"No qrels found in {path}.")
    return qrels


# -- benchmark --------------------------------------------------------------


def score_query(
    qrel: Qrel, ranked: Sequence[str], ks: Sequence[int]
) -> dict[str, Any]:
    """Score one query's ranked chunk ids against its qrels."""
    scores: dict[str, Any] = {
        "id": qrel.id,
        "category": qrel.category,
        "mrr": reciprocal_rank(ranked, qrel.relevant_chunk_ids),
        "missing_relevant_chunk_ids": [
            chunk_id
            for chunk_id in qrel.relevant_chunk_ids
            if chunk_id not in ranked
        ],
    }
    for k in ks:
        scores[f"recall@{k}"] = recall_at_k(ranked, qrel.relevant_chunk_ids, k)
        scores[f"precision@{k}"] = precision_at_k(
            ranked, qrel.relevant_chunk_ids, k
        )
        scores[f"ndcg@{k}"] = ndcg_at_k(ranked, qrel.relevant_chunk_ids, k)
    return scores


def run_benchmark(
    retrieval: Any,
    qrels: Sequence[Qrel],
    *,
    strategies: Sequence[str] = SEARCH_STRATEGIES,
    ks: Sequence[int] = DEFAULT_KS,
) -> dict[str, Any]:
    """Run every strategy over every query and aggregate the metrics.

    ``retrieval`` only needs a ``search(query, top_k=..., document_id=...,
    strategy=...)`` method, so the benchmark runs against a stub in tests.
    """
    if not qrels:
        raise ValueError("The benchmark needs at least one labeled question.")
    for strategy in strategies:
        if strategy not in SEARCH_STRATEGIES:
            raise ValueError(f"Unknown retrieval strategy: {strategy}")
    ordered_ks = sorted({int(k) for k in ks})
    if not ordered_ks or ordered_ks[0] <= 0:
        raise ValueError("All k values must be positive.")
    depth = max(ordered_ks)

    report: dict[str, Any] = {
        "question_count": len(qrels),
        "ks": ordered_ks,
        "strategies": {},
        "metric_notes": {
            "relevance": "Binary; a chunk is relevant only if it is in the qrels.",
            "qrels": "Small, single-annotator labels for the local demo corpus.",
            "scope": "Retrieval only; no generation, verification or abstention.",
            "ndcg": "Binary gains; ideal DCG uses the number of labeled chunks.",
        },
    }

    for strategy in strategies:
        per_case: list[dict[str, Any]] = []
        for qrel in qrels:
            results: list[RetrievalResult] = retrieval.search(
                qrel.question,
                top_k=depth,
                document_id=qrel.document_id,
                strategy=strategy,
            )
            per_case.append(
                score_query(qrel, [item.chunk_id for item in results], ordered_ks)
            )

        metrics: dict[str, Any] = {"mrr": _average(per_case, "mrr")}
        for k in ordered_ks:
            for name in ("recall", "precision", "ndcg"):
                key = f"{name}@{k}"
                metrics[key] = _average(per_case, key)
        report["strategies"][strategy] = {
            "metrics": metrics,
            "cases": per_case,
        }
    return report


def _average(rows: Sequence[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return mean(values) if values else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default_qrels = (
        Path(__file__).resolve().parents[1] / "evaluation" / "retrieval_qrels.jsonl"
    )
    parser.add_argument("--qrels", type=Path, default=default_qrels)
    parser.add_argument("--ks", default=",".join(str(k) for k in DEFAULT_KS))
    parser.add_argument(
        "--strategies", default=",".join(SEARCH_STRATEGIES)
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    ks = [int(value) for value in args.ks.split(",") if value.strip()]
    strategies = [value.strip() for value in args.strategies.split(",") if value.strip()]

    # Imported lazily so the metric functions stay importable without the E5
    # model: the CLI needs the real index, the tests do not.
    from app.services.retrieval_service import get_retrieval_service

    report = run_benchmark(
        get_retrieval_service(),
        load_qrels(args.qrels),
        strategies=strategies,
        ks=ks,
    )
    report["retrieval_strategy"] = DEFAULT_STRATEGY
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
