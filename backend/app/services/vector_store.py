"""Vector store abstraction with a NumPy exact-cosine backend.

FAISS is unavailable on this machine (Windows Smart App Control blocks the
DLL), so the default backend is brute-force cosine similarity in NumPy. The
:class:`VectorStore` interface is backend-agnostic: adding a FAISS backend
later only requires implementing the same methods.

Persistence is a single ``.npz`` file holding the vector matrix and a JSON
metadata blob, so matrix and metadata can never drift apart. Writes use a
temporary file followed by ``os.replace``.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np

logger = logging.getLogger(__name__)

INDEX_VERSION = 1
INDEX_BACKEND = "numpy"
INDEX_FILENAME = "vector_index.npz"
DEFAULT_TOP_K = 6


class VectorStoreError(RuntimeError):
    """Vectors, metadata or the persisted index are inconsistent."""


@dataclass(frozen=True)
class SearchResult:
    """One ranked hit."""

    chunk_id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStore(ABC):
    """Minimal interface every vector backend must provide."""

    def __init__(self, dimension: int, model_name: str) -> None:
        if dimension <= 0:
            raise VectorStoreError("Vector dimension must be positive.")
        self.dimension = dimension
        self.model_name = model_name

    @abstractmethod
    def add(
        self,
        vectors: np.ndarray,
        chunk_ids: Sequence[str],
        metadata: Sequence[dict[str, Any]] | None = None,
        *,
        persist: bool = True,
    ) -> int:
        """Add vectors; returns the number added."""

    @abstractmethod
    def search(
        self, query_vector: np.ndarray, top_k: int = DEFAULT_TOP_K
    ) -> list[SearchResult]:
        """Return up to ``top_k`` hits, highest cosine similarity first."""

    @abstractmethod
    def save(self) -> None:
        """Persist the index atomically."""

    @abstractmethod
    def load(self) -> None:
        """Load the persisted index, or start empty when none exists."""

    @abstractmethod
    def remove_document(self, document_id: str) -> int:
        """Remove every vector belonging to a document; returns the count."""

    @abstractmethod
    def __len__(self) -> int: ...


class NumpyVectorStore(VectorStore):
    """Exact cosine similarity over a dense ``float32`` matrix."""

    def __init__(
        self,
        directory: Path,
        dimension: int,
        model_name: str,
        *,
        filename: str = INDEX_FILENAME,
        autoload: bool = True,
    ) -> None:
        super().__init__(dimension, model_name)
        self.directory = Path(directory)
        self.filename = filename
        self._matrix = np.zeros((0, dimension), dtype=np.float32)
        self._chunk_ids: list[str] = []
        self._metadata: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        if autoload:
            self.load()

    # -- helpers -------------------------------------------------------

    @property
    def path(self) -> Path:
        return self.directory / self.filename

    @property
    def chunk_ids(self) -> list[str]:
        return list(self._chunk_ids)

    @property
    def metadata(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._metadata]

    def _validate_vectors(self, vectors: np.ndarray) -> np.ndarray:
        array = np.asarray(vectors, dtype=np.float32)
        if array.size == 0:
            return np.zeros((0, self.dimension), dtype=np.float32)
        if array.ndim != 2:
            raise VectorStoreError(
                f"Expected a 2-D vector matrix, received shape {array.shape}."
            )
        if array.shape[1] != self.dimension:
            raise VectorStoreError(
                f"Vector dimension mismatch: index expects {self.dimension}, "
                f"received {array.shape[1]}."
            )
        if not np.all(np.isfinite(array)):
            raise VectorStoreError("Vectors contain non-finite values.")
        # Normalise so stored dot products really are cosine similarities.
        # Zero rows are left as zeros (they score 0 against every query).
        norms = np.linalg.norm(array, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (array / norms).astype(np.float32)

    def _validate_query(self, query_vector: np.ndarray) -> np.ndarray:
        query = np.asarray(query_vector, dtype=np.float32).reshape(-1)
        if query.shape[0] != self.dimension:
            raise VectorStoreError(
                f"Query dimension mismatch: index expects {self.dimension}, "
                f"received {query.shape[0]}."
            )
        if not np.all(np.isfinite(query)):
            raise VectorStoreError("Query vector contains non-finite values.")
        norm = float(np.linalg.norm(query))
        if norm == 0.0:
            raise VectorStoreError("Query vector must not be all zeros.")
        return query / norm

    # -- mutation ------------------------------------------------------

    def add(
        self,
        vectors: np.ndarray,
        chunk_ids: Sequence[str],
        metadata: Sequence[dict[str, Any]] | None = None,
        *,
        persist: bool = True,
    ) -> int:
        array = self._validate_vectors(vectors)
        ids = [str(chunk_id) for chunk_id in chunk_ids]
        if array.shape[0] != len(ids):
            raise VectorStoreError(
                f"Received {array.shape[0]} vectors for {len(ids)} chunk IDs."
            )
        if not ids:
            return 0
        if any(not chunk_id.strip() for chunk_id in ids):
            raise VectorStoreError("Chunk IDs must not be empty.")
        if len(set(ids)) != len(ids):
            raise VectorStoreError("Duplicate chunk IDs in one batch are not allowed.")

        entries = (
            [dict(item) for item in metadata]
            if metadata is not None
            else [{} for _ in ids]
        )
        if len(entries) != len(ids):
            raise VectorStoreError(
                f"Received {len(entries)} metadata records for {len(ids)} chunk IDs."
            )

        with self._lock:
            existing = set(self._chunk_ids)
            duplicates = existing.intersection(ids)
            if duplicates:
                raise VectorStoreError(
                    f"{len(duplicates)} chunk ID(s) already exist in the index."
                )
            self._matrix = np.vstack([self._matrix, array.astype(np.float32)])
            self._chunk_ids.extend(ids)
            self._metadata.extend(entries)
            if persist:
                self.save()
        return len(ids)

    def remove_document(self, document_id: str) -> int:
        with self._lock:
            keep = [
                index
                for index, item in enumerate(self._metadata)
                if item.get("document_id") != document_id
            ]
            removed = len(self._chunk_ids) - len(keep)
            if removed:
                self._matrix = self._matrix[keep]
                self._chunk_ids = [self._chunk_ids[i] for i in keep]
                self._metadata = [self._metadata[i] for i in keep]
        return removed

    # -- search --------------------------------------------------------

    def search(
        self, query_vector: np.ndarray, top_k: int = DEFAULT_TOP_K
    ) -> list[SearchResult]:
        if top_k <= 0:
            raise ValueError("top_k must be positive.")
        query = self._validate_query(query_vector)
        with self._lock:
            if not self._chunk_ids:
                return []
            scores = self._matrix @ query
            order = np.argsort(-scores, kind="stable")[: min(top_k, len(scores))]
            return [
                SearchResult(
                    chunk_id=self._chunk_ids[int(index)],
                    score=float(scores[int(index)]),
                    metadata=dict(self._metadata[int(index)]),
                )
                for index in order
            ]

    # -- persistence ---------------------------------------------------

    def save(self) -> None:
        with self._lock:
            payload = {
                "version": INDEX_VERSION,
                "backend": INDEX_BACKEND,
                "model": self.model_name,
                "dimension": self.dimension,
                "count": len(self._chunk_ids),
                "chunk_ids": self._chunk_ids,
                "metadata": self._metadata,
            }
            self.directory.mkdir(parents=True, exist_ok=True)
            handle, tmp_name = tempfile.mkstemp(
                dir=self.directory, prefix=".vector_index.", suffix=".tmp.npz"
            )
            os.close(handle)
            try:
                np.savez_compressed(
                    tmp_name,
                    matrix=self._matrix,
                    meta=np.array([json.dumps(payload, ensure_ascii=False)]),
                )
                os.replace(tmp_name, self.path)
            except BaseException:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
                raise

    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self._matrix = np.zeros((0, self.dimension), dtype=np.float32)
                self._chunk_ids = []
                self._metadata = []
                return
            try:
                with np.load(self.path, allow_pickle=False) as data:
                    matrix = np.asarray(data["matrix"], dtype=np.float32)
                    meta = json.loads(str(data["meta"][0]))
            except Exception as exc:  # noqa: BLE001 - corrupted index
                raise VectorStoreError(
                    f"The vector index at {self.path} is unreadable."
                ) from exc

            if not isinstance(meta, dict):
                raise VectorStoreError("The vector index metadata is malformed.")
            if int(meta.get("version", -1)) != INDEX_VERSION:
                raise VectorStoreError(
                    f"Unsupported vector index version {meta.get('version')!r}."
                )
            if int(meta.get("dimension", -1)) != self.dimension:
                raise VectorStoreError(
                    "The stored vector index was built with dimension "
                    f"{meta.get('dimension')} but {self.dimension} is configured."
                )
            if str(meta.get("model", "")) != self.model_name:
                raise VectorStoreError(
                    "The stored vector index was built with model "
                    f"'{meta.get('model')}' but '{self.model_name}' is configured."
                )

            chunk_ids = [str(item) for item in meta.get("chunk_ids", [])]
            metadata = [dict(item) for item in meta.get("metadata", [])]
            if matrix.ndim != 2 or matrix.shape[1] != self.dimension:
                raise VectorStoreError("The stored vector matrix has a bad shape.")
            if matrix.shape[0] != len(chunk_ids) or len(metadata) != len(chunk_ids):
                raise VectorStoreError(
                    "The stored vector index has inconsistent counts."
                )

            self._matrix = matrix
            self._chunk_ids = chunk_ids
            self._metadata = metadata
            logger.info("Loaded %s vectors from %s", len(chunk_ids), self.path)

    def __len__(self) -> int:
        return len(self._chunk_ids)


_stores: dict[tuple[str, str, int], NumpyVectorStore] = {}
_stores_lock = threading.Lock()


def vector_index_dir(data_dir: Path) -> Path:
    return data_dir / "indexes" / "vectors"


def get_vector_store(
    data_dir: Path,
    *,
    model_name: str,
    dimension: int,
) -> NumpyVectorStore:
    """Return the shared vector store for this data directory and model."""
    directory = vector_index_dir(data_dir)
    key = (str(directory), model_name, dimension)
    with _stores_lock:
        store = _stores.get(key)
        if store is None:
            store = NumpyVectorStore(directory, dimension, model_name)
            _stores[key] = store
        return store


def reset_vector_stores() -> None:
    """Forget cached stores (used by tests)."""
    with _stores_lock:
        _stores.clear()
