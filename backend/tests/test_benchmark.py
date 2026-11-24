"""Retrieval benchmark metrics, qrels validation and strategy ablations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.benchmark import (
    Qrel,
    load_qrels,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    run_benchmark,
    score_query,
)


# -- metric maths -----------------------------------------------------------


def test_recall_precision_and_mrr_on_a_known_ranking() -> None:
    ranked = ["a", "b", "c", "d"]
    relevant = ["b", "d"]

    assert recall_at_k(ranked, relevant, 1) == 0.0
    assert recall_at_k(ranked, relevant, 2) == pytest.approx(0.5)
    assert recall_at_k(ranked, relevant, 4) == pytest.approx(1.0)
    assert precision_at_k(ranked, relevant, 2) == pytest.approx(0.5)
    assert precision_at_k(ranked, relevant, 4) == pytest.approx(0.5)
    assert reciprocal_rank(ranked, relevant) == pytest.approx(0.5)


def test_reciprocal_rank_is_zero_when_nothing_relevant_is_returned() -> None:
    assert reciprocal_rank(["a", "b"], ["z"]) == 0.0


def test_ndcg_matches_the_hand_computed_value() -> None:
    # Relevant at ranks 2 and 4; ideal DCG puts them at ranks 1 and 2.
    ranked = ["a", "b", "c", "d"]
    relevant = ["b", "d"]
    dcg = 1.0 / __import__("math").log2(3) + 1.0 / __import__("math").log2(5)
    ideal = 1.0 + 1.0 / __import__("math").log2(3)

    assert ndcg_at_k(ranked, relevant, 4) == pytest.approx(dcg / ideal)
    # A perfect ranking scores 1.0.
    assert ndcg_at_k(["b", "d"], relevant, 2) == pytest.approx(1.0)


def test_metrics_reject_impossible_inputs() -> None:
    with pytest.raises(ValueError):
        recall_at_k(["a"], [], 1)
    with pytest.raises(ValueError):
        recall_at_k(["a"], ["a"], 0)
    with pytest.raises(ValueError):
        ndcg_at_k(["a"], ["a"], 0)
    with pytest.raises(ValueError):
        precision_at_k(["a"], ["a"], 0)


# -- dataset ----------------------------------------------------------------


def _write_qrels(path: Path, entries: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8"
    )
    return path


def test_load_qrels_reads_valid_entries(tmp_path: Path) -> None:
    path = _write_qrels(
        tmp_path / "qrels.jsonl",
        [
            {
                "id": "q1",
                "question": "What is the rent?",
                "relevant_chunk_ids": ["c1", "c1", "c2"],
            }
        ],
    )

    qrels = load_qrels(path)

    assert [qrel.id for qrel in qrels] == ["q1"]
    # Duplicate labels collapse so recall cannot exceed 1.
    assert qrels[0].relevant_chunk_ids == ("c1", "c2")
    assert qrels[0].document_id is None


@pytest.mark.parametrize(
    "entry",
    [
        {"question": "no id", "relevant_chunk_ids": ["c1"]},
        {"id": "q", "relevant_chunk_ids": ["c1"]},
        {"id": "q", "question": "no labels", "relevant_chunk_ids": []},
        {"id": "q", "question": "blank labels", "relevant_chunk_ids": ["  "]},
    ],
)
def test_load_qrels_rejects_incomplete_entries(
    tmp_path: Path, entry: dict
) -> None:
    path = _write_qrels(tmp_path / "qrels.jsonl", [entry])
    with pytest.raises(ValueError):
        load_qrels(path)


def test_load_qrels_rejects_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "qrels.jsonl"
    path.write_text("\n\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_qrels(path)


# -- benchmark --------------------------------------------------------------


class StubRetrieval:
    """Returns a fixed ranking per strategy and records the calls it receives."""

    def __init__(self, rankings: dict[str, list[str]]) -> None:
        self._rankings = rankings
        self.calls: list[dict] = []

    def search(self, query, *, top_k=None, document_id=None, strategy=None):
        self.calls.append(
            {"query": query, "top_k": top_k, "document_id": document_id, "strategy": strategy}
        )

        class Hit:
            def __init__(self, chunk_id: str) -> None:
                self.chunk_id = chunk_id

        return [Hit(chunk_id) for chunk_id in self._rankings.get(strategy, [])[:top_k]]


def test_run_benchmark_reports_every_strategy_and_k() -> None:
    qrels = [
        Qrel(
            id="q1",
            question="What is the rent?",
            relevant_chunk_ids=("c2",),
        )
    ]
    retrieval = StubRetrieval(
        {
            "hybrid_rerank": ["c2", "c1"],
            "hybrid": ["c1", "c2"],
            "semantic": ["c1", "c2"],
            "keyword": [],
        }
    )

    report = run_benchmark(
        retrieval, qrels, strategies=("hybrid_rerank", "hybrid"), ks=(1, 2)
    )

    assert report["question_count"] == 1
    reranked = report["strategies"]["hybrid_rerank"]["metrics"]
    fused = report["strategies"]["hybrid"]["metrics"]
    assert reranked["recall@1"] == 1.0
    assert reranked["mrr"] == 1.0
    assert fused["recall@1"] == 0.0
    assert fused["recall@2"] == 1.0
    assert fused["mrr"] == pytest.approx(0.5)
    assert report["strategies"]["hybrid"]["cases"][0]["missing_relevant_chunk_ids"] == []


def test_run_benchmark_records_misses_and_rejects_bad_input() -> None:
    qrels = [Qrel(id="q1", question="q", relevant_chunk_ids=("c9",))]
    report = run_benchmark(
        StubRetrieval({"semantic": ["c1"]}), qrels, strategies=("semantic",), ks=(3,)
    )

    case = report["strategies"]["semantic"]["cases"][0]
    assert case["missing_relevant_chunk_ids"] == ["c9"]
    assert case["recall@3"] == 0.0
    assert case["ndcg@3"] == 0.0

    with pytest.raises(ValueError):
        run_benchmark(StubRetrieval({}), [], strategies=("semantic",))
    with pytest.raises(ValueError):
        run_benchmark(StubRetrieval({}), qrels, strategies=("nonsense",))
    with pytest.raises(ValueError):
        run_benchmark(StubRetrieval({}), qrels, strategies=("semantic",), ks=(0,))


def test_score_query_reports_per_k_metrics() -> None:
    qrel = Qrel(id="q", question="q", relevant_chunk_ids=("b",), category="cat")
    row = score_query(qrel, ["a", "b", "c"], (1, 3))

    assert row["category"] == "cat"
    assert row["recall@1"] == 0.0
    assert row["recall@3"] == 1.0
    assert row["precision@3"] == pytest.approx(1 / 3)
    assert row["mrr"] == pytest.approx(0.5)
