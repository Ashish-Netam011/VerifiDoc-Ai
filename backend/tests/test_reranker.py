"""Relevance reranking stays separate from the NLI verification model."""

from __future__ import annotations

import numpy as np
import pytest

from app.services.reranker_service import RerankerError, RerankerService


class StubCrossEncoder:
    def __init__(self, values) -> None:
        self.values = values
        self.calls = []

    def predict(self, pairs, **kwargs):
        self.calls.append((pairs, kwargs))
        return self.values


def test_reranker_returns_raw_finite_scores_in_input_order(tmp_path) -> None:
    service = RerankerService("local/model", tmp_path)
    model = StubCrossEncoder(np.array([0.2, 0.9], dtype=np.float32))
    service._model = model

    scores = service.score("rent question", ["low relevance", "high relevance"])

    assert scores == pytest.approx([0.2, 0.9])
    assert model.calls[0][0] == [
        ("rent question", "low relevance"),
        ("rent question", "high relevance"),
    ]
    assert model.calls[0][1]["apply_softmax"] is False


def test_reranker_rejects_non_finite_scores(tmp_path) -> None:
    service = RerankerService("local/model", tmp_path)
    service._model = StubCrossEncoder(np.array([np.nan], dtype=np.float32))

    with pytest.raises(RerankerError, match="Reranker returned"):
        service.score("query", ["candidate"])


def test_missing_reranker_checkpoint_fails_without_fallback(tmp_path) -> None:
    service = RerankerService("uncached/relevance-model", tmp_path)

    with pytest.raises(RerankerError, match="No download was attempted"):
        service.score("query", ["candidate"])
