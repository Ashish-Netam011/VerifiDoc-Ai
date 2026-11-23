"""Real-model embedding tests using the cached intfloat/multilingual-e5-small.

These load the actual checkpoint from ``data/models_cache`` (about 4 s once) and
verify dimension, normalisation, E5 prefixes and a small ranking smoke check.
They are not a benchmark of model quality.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.config import get_settings
from app.services.embedding_service import (
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    EmbeddingModelError,
    EmbeddingService,
)


@pytest.fixture(scope="module")
def service() -> EmbeddingService:
    settings = get_settings()
    return EmbeddingService(
        settings.embed_model,
        settings.model_cache_dir,
        batch_size=settings.embed_batch_size,
        expected_dim=settings.embed_dim,
    )


def test_embedding_dimension_is_384(service: EmbeddingService) -> None:
    assert service.model_name == "intfloat/multilingual-e5-small"
    assert service.expected_dimension == 384
    vectors = service.embed_passages(["The tenant shall pay rent on the first day."])
    assert vectors.shape == (1, 384)
    assert vectors.dtype == np.float32


def test_embeddings_are_normalized(service: EmbeddingService) -> None:
    vectors = service.embed_passages(
        [
            "The agreement may be amended only in writing.",
            "This contract is governed by the laws of California.",
        ]
    )
    norms = np.linalg.norm(vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_empty_input_is_safe(service: EmbeddingService) -> None:
    empty = service.embed_passages([])
    assert empty.shape == (0, 384)
    assert empty.dtype == np.float32


def test_blank_text_is_rejected(service: EmbeddingService) -> None:
    with pytest.raises(ValueError):
        service.embed_passages(["   "])
    with pytest.raises(ValueError):
        service.embed_query("")


def test_e5_prefixes_are_used(service: EmbeddingService) -> None:
    model = service.ensure_loaded()
    text = "rent is due on the first of the month"

    passage = service.embed_passages([text])[0]
    expected_passage = model.encode(
        [PASSAGE_PREFIX + text],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0]
    np.testing.assert_allclose(passage, expected_passage, atol=1e-6)

    query = service.embed_query(text)
    expected_query = model.encode(
        [QUERY_PREFIX + text],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )[0]
    np.testing.assert_allclose(query, expected_query, atol=1e-6)

    # The prefix must actually change the vector, not be cosmetic.
    assert not np.allclose(passage, query, atol=1e-3)


def test_related_passage_ranks_above_unrelated(service: EmbeddingService) -> None:
    passages = {
        "rent": "The tenant shall pay the monthly rent on the first day of each month.",
        "amendment": "This agreement may be amended only by a written instrument signed by both parties.",
        "governing_law": "This agreement is governed by the laws of the State of California.",
        "notices": "All notices must be delivered in writing to the address in Schedule A.",
        "termination": "Either party may terminate this agreement with thirty days written notice.",
    }
    ids = list(passages)
    matrix = service.embed_passages([passages[key] for key in ids])
    query = service.embed_query("When is the rent payment due?")
    scores = matrix @ query

    ranking = [ids[int(index)] for index in np.argsort(-scores)]
    assert ranking[0] == "rent"
    assert scores[ids.index("rent")] > scores[ids.index("governing_law")]


def test_missing_model_reports_clear_error(tmp_path) -> None:
    broken = EmbeddingService(
        "intfloat/definitely-not-cached-model",
        tmp_path,
        expected_dim=384,
    )
    with pytest.raises(EmbeddingModelError, match="could not be loaded"):
        broken.embed_passages(["hello"])
