"""Local query-document relevance reranking, kept separate from NLI verification."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Sequence

import numpy as np

from app.services.model_cache import ModelNotCachedError, resolve_local_snapshot

logger = logging.getLogger(__name__)


class RerankerError(RuntimeError):
    """The relevance reranker is unavailable or returned invalid scores."""


class RerankerService:
    """Lazy, thread-safe wrapper around a scalar relevance CrossEncoder."""

    def __init__(
        self,
        model_name: str,
        cache_dir: Path,
        *,
        device: str = "cpu",
        max_length: int = 512,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = Path(cache_dir)
        self._device = device
        self._max_length = max_length
        self._model: object | None = None
        self._load_lock = threading.Lock()
        self._predict_lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    def _ensure_loaded(self) -> object:
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:  # pragma: no cover - pinned dependency
                raise RerankerError("sentence-transformers is not installed.") from exc

            try:
                snapshot = resolve_local_snapshot(self._model_name, self._cache_dir)
            except ModelNotCachedError as exc:
                raise RerankerError(str(exc)) from exc

            try:
                model = CrossEncoder(
                    str(snapshot),
                    device=self._device,
                    local_files_only=True,
                    max_length=self._max_length,
                )
            except Exception as exc:  # noqa: BLE001 - surfaced as a typed API error
                raise RerankerError(
                    f"Relevance model '{self._model_name}' could not be loaded."
                ) from exc

            self._model = model
            logger.info("Loaded relevance reranker %s from %s", self._model_name, snapshot)
            return model

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """Return one raw query-passage relevance score per passage."""
        if not query.strip():
            raise ValueError("Reranker query must not be empty.")
        if not passages:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in passages):
            raise ValueError("Reranker passages must not be empty.")

        model = self._ensure_loaded()
        pairs = [(query.strip(), text.strip()) for text in passages]
        try:
            with self._predict_lock:
                values = model.predict(  # type: ignore[attr-defined]
                    pairs,
                    apply_softmax=False,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
        except Exception as exc:  # noqa: BLE001 - surfaced as a typed API error
            raise RerankerError("Relevance reranking failed.") from exc

        scores = np.asarray(values, dtype=np.float32).reshape(-1)
        if scores.shape != (len(pairs),) or not np.all(np.isfinite(scores)):
            raise RerankerError(
                f"Reranker returned {scores.shape} scores for {len(pairs)} passages."
            )
        return [float(score) for score in scores]


_service: RerankerService | None = None
_service_lock = threading.Lock()


def get_reranker_service() -> RerankerService:
    """Return the process-wide, lazily loaded local relevance model."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                from app.config import get_settings

                settings = get_settings()
                _service = RerankerService(
                    settings.reranker_model,
                    settings.model_cache_dir,
                )
    return _service


def reset_reranker_service() -> None:
    """Forget the cached service (used by tests)."""
    global _service
    with _service_lock:
        _service = None
