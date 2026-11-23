"""Real NLI model tests using the cached cross-encoder/nli-deberta-base.

Loads the actual checkpoint from data/models_cache (about 1 s) and checks the
label mapping read from the model config, plus the three relation classes.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.services.nli_service import (
    NLIError,
    NLIService,
    resolve_local_snapshot,
)

PREMISE = (
    "1. RENT The Tenant shall pay a monthly rent of INR 15,000, due on the fifth "
    "day of each calendar month. A late payment attracts interest of 2% per month."
)

ENTAILMENT_CLAIM = "The monthly rent is INR 15,000."
CONTRADICTION_CLAIM = "The monthly rent is INR 18,000."
NEUTRAL_CLAIM = "The lease is governed by German law."


@pytest.fixture(scope="module")
def service() -> NLIService:
    settings = get_settings()
    return NLIService(
        settings.nli_model,
        settings.model_cache_dir,
        batch_size=settings.nli_batch_size,
    )


def test_model_loads_offline(service: NLIService) -> None:
    model = service.ensure_loaded()
    assert model is not None
    assert service.model_path is not None and service.model_path.is_dir()
    assert service.model_path.is_relative_to(get_settings().model_cache_dir)


def test_label_mapping_comes_from_model_config(service: NLIService) -> None:
    service.ensure_loaded()
    config_path = service.model_path / "config.json"  # type: ignore[operator]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    expected = {str(label).lower(): int(index) for index, label in config["id2label"].items()}

    assert service.label_index == expected
    # Guard against the common wrong assumption that entailment is class 2.
    assert service.label_index["entailment"] == expected["entailment"]
    assert service.label_for(service.label_index["contradiction"]) == "contradiction"
    assert sorted(service.label_index.values()) == [0, 1, 2]


def test_entailment_example(service: NLIService) -> None:
    scores = service.score_pairs([(PREMISE, ENTAILMENT_CLAIM)])[0]
    assert scores.entailment > 0.6
    assert scores.entailment > scores.contradiction
    assert scores.best_label == "entailment"


def test_contradiction_example(service: NLIService) -> None:
    scores = service.score_pairs([(PREMISE, CONTRADICTION_CLAIM)])[0]
    assert scores.contradiction > 0.6
    assert scores.contradiction > scores.entailment
    assert scores.best_label == "contradiction"


def test_neutral_example(service: NLIService) -> None:
    scores = service.score_pairs([(PREMISE, NEUTRAL_CLAIM)])[0]
    assert scores.neutral > 0.6
    assert scores.best_label == "neutral"


def test_negation_is_not_entailment(service: NLIService) -> None:
    premise = (
        "The Tenant may not sublet the premises without the Landlord's written consent."
    )
    hypothesis = "The Tenant may sublet the premises."
    scores = service.score_pairs([(premise, hypothesis)])[0]
    assert scores.entailment < 0.5
    assert scores.contradiction > scores.entailment


def test_batch_scores_are_well_formed(service: NLIService) -> None:
    pairs = [(PREMISE, ENTAILMENT_CLAIM), (PREMISE, CONTRADICTION_CLAIM), (PREMISE, NEUTRAL_CLAIM)]
    results = service.score_pairs(pairs)
    assert len(results) == 3
    for scores in results:
        assert scores.entailment + scores.neutral + scores.contradiction == pytest.approx(1.0, abs=1e-3)
    assert service.score_pairs([]) == []


def test_blank_inputs_are_rejected(service: NLIService) -> None:
    with pytest.raises(ValueError):
        service.score_pairs([("   ", "claim")])
    with pytest.raises(ValueError):
        service.score_pairs([("premise", "")])


def test_missing_model_fails_explicitly(tmp_path: Path) -> None:
    with pytest.raises(NLIError, match="not present in the local cache"):
        resolve_local_snapshot("cross-encoder/definitely-not-cached", tmp_path)

    broken = NLIService("cross-encoder/definitely-not-cached", tmp_path)
    with pytest.raises(NLIError):
        broken.score_pairs([("premise", "hypothesis")])


def test_unusable_label_mapping_is_rejected(tmp_path: Path) -> None:
    service = NLIService("irrelevant", tmp_path)

    good = SimpleNamespace(
        model=SimpleNamespace(
            config=SimpleNamespace(id2label={0: "contradiction", 1: "entailment", 2: "neutral"})
        )
    )
    assert service._read_label_mapping(good) == {
        "contradiction": 0,
        "entailment": 1,
        "neutral": 2,
    }

    with pytest.raises(NLIError, match="Unexpected NLI label"):
        service._read_label_mapping(
            SimpleNamespace(
                model=SimpleNamespace(config=SimpleNamespace(id2label={0: "contradiction", 1: "foo"}))
            )
        )

    with pytest.raises(NLIError, match="id2label"):
        service._read_label_mapping(SimpleNamespace(model=SimpleNamespace(config=SimpleNamespace())))

    with pytest.raises(NLIError, match="incomplete"):
        service._read_label_mapping(
            SimpleNamespace(
                model=SimpleNamespace(
                    config=SimpleNamespace(id2label={0: "contradiction", 1: "entailment"})
                )
            )
        )
