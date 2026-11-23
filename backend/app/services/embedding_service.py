"""E5 embeddings from the locally cached Sentence Transformers model.

Design notes:

* the model is loaded lazily, once per process, and never downloaded here -
  ``local_files_only=True`` makes a missing cache an explicit error instead of
  a silent network fetch of some other checkpoint;
* E5 expects ``passage: `` on documents and ``query: `` on questions, so the
  prefixes are applied inside this service and callers pass plain text;
* vectors are L2-normalised, which lets cosine similarity be a dot product;
* no random or alternative model is ever substituted on failure.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)

PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "
E5_DEFAULT_DIM = 384


class EmbeddingModelError(RuntimeError):
    """The embedding model could not be loaded or produced invalid output."""


class EmbeddingService:
    """Lazy, thread-safe wrapper around a Sentence Transformers model."""

    def __init__(
        self,
        model_name: str,
        cache_dir: Path,
        *,
        batch_size: int = 16,
        expected_dim: int = E5_DEFAULT_DIM,
        device: str = "cpu",
    ) -> None:
        self._model_name = model_name
        self._cache_dir = Path(cache_dir)
        self._batch_size = batch_size
        self._expected_dim = expected_dim
        self._device = device
        self._model: object | None = None
        self._load_lock = threading.Lock()

    # -- introspection -------------------------------------------------

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def expected_dimension(self) -> int:
        return self._expected_dim

    @property
    def batch_size(self) -> int:
        return self._batch_size

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    # -- loading -------------------------------------------------------

    def _model_dimension(self, model: object) -> int:
        getter = getattr(model, "get_embedding_dimension", None)
        if getter is None:  # Sentence Transformers < 6
            getter = getattr(model, "get_sentence_embedding_dimension", None)
        if getter is None:
            raise EmbeddingModelError("The embedding model reports no dimension.")
        return int(getter())

    def ensure_loaded(self) -> object:
        """Load the model on first use and return it."""
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - dependency is pinned
                raise EmbeddingModelError(
                    "sentence-transformers is not installed in this environment."
                ) from exc
            except Exception as exc:
                raise EmbeddingModelError(
                    f"Embedding runtime could not import model dependencies: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

            try:
                import torch

                try:
                    torch.set_num_threads(1)
                except RuntimeError as exc:
                    logger.warning("Could not set PyTorch intra-op threads: %s", exc)

                # set_num_interop_threads can only be called before PyTorch starts
                # parallel work. Treat an already-started runtime as normal, rather
                # than making model loading fail after work has begun.
                if hasattr(torch, "set_num_interop_threads"):
                    try:
                        torch.set_num_interop_threads(1)
                    except RuntimeError as exc:
                        if "parallel work has started" not in str(exc).lower():
                            raise
                        logger.debug(
                            "PyTorch inter-op threads already configured: %s", exc
                        )
            except Exception as exc:
                raise EmbeddingModelError(
                    f"Embedding runtime could not configure PyTorch: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

            try:
                model = SentenceTransformer(
                    self._model_name,
                    cache_folder=str(self._cache_dir),
                    device=self._device,
                    local_files_only=True,
                )
            except Exception as exc:  # noqa: BLE001 - surfaced as a typed error
                raise EmbeddingModelError(
                    f"Embedding model '{self._model_name}' could not be loaded "
                    f"from the local cache at {self._cache_dir}. "
                    "No download was attempted."
                ) from exc

            dimension = self._model_dimension(model)
            if dimension != self._expected_dim:
                raise EmbeddingModelError(
                    f"Embedding model '{self._model_name}' produces {dimension}-"
                    f"dimensional vectors but {self._expected_dim} were expected."
                )

            self._model = model
            logger.info(
                "Loaded embedding model %s (%s dims) from %s",
                self._model_name,
                dimension,
                self._cache_dir,
            )
        return self._model

    # -- encoding ------------------------------------------------------

    def _empty_matrix(self) -> np.ndarray:
        return np.zeros((0, self._expected_dim), dtype=np.float32)

    def _encode(self, texts: list[str], prefix: str) -> np.ndarray:
        if not texts:
            return self._empty_matrix()

        prepared: list[str] = []
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Cannot embed empty or whitespace-only text.")
            prepared.append(prefix + text.strip())

        model = self.ensure_loaded()
        try:
            vectors = model.encode(  # type: ignore[attr-defined]
                prepared,
                batch_size=self._batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as exc:  # noqa: BLE001 - typed for the API layer
            raise EmbeddingModelError("Embedding generation failed.") from exc

        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[1] != self._expected_dim:
            raise EmbeddingModelError(
                f"Embedding output had shape {matrix.shape}, expected "
                f"(n, {self._expected_dim})."
            )
        if not np.all(np.isfinite(matrix)):
            raise EmbeddingModelError("Embedding output contained non-finite values.")

        # Defensive re-normalisation: cosine search assumes unit vectors.
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (matrix / norms).astype(np.float32)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        """Embed document chunks (``passage: `` prefix)."""
        return self._encode(list(texts), PASSAGE_PREFIX)

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a search query (``query: `` prefix)."""
        return self._encode([text], QUERY_PREFIX)[0]

    # -- async helpers -------------------------------------------------

    async def aembed_passages(self, texts: list[str]) -> np.ndarray:
        """Run CPU-bound encoding off the event loop."""
        return await asyncio.to_thread(self.embed_passages, texts)

    async def aembed_query(self, text: str) -> np.ndarray:
        return await asyncio.to_thread(self.embed_query, text)


_service: EmbeddingService | None = None
_service_lock = threading.Lock()


def get_embedding_service() -> EmbeddingService:
    """Process-wide embedding service (model loads on first use)."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                settings = get_settings()
                _service = EmbeddingService(
                    settings.embed_model,
                    settings.model_cache_dir,
                    batch_size=settings.embed_batch_size,
                    expected_dim=settings.embed_dim,
                )
    return _service


def reset_embedding_service() -> None:
    """Drop the cached service (used by tests)."""
    global _service
    with _service_lock:
        _service = None
