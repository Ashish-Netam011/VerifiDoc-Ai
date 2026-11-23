"""Natural-language-inference scoring with the cached DeBERTa cross-encoder.

Label order is read from the model's own configuration. For
``cross-encoder/nli-deberta-base`` it is ``0=contradiction, 1=entailment,
2=neutral`` - which is *not* the common ``entailment=2`` layout, so nothing here
assumes an index. If the mapping cannot be established safely, loading fails.

The model is loaded from an already-cached snapshot; ``local_files_only=True``
means a missing cache raises instead of downloading another checkpoint.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.config import get_settings

logger = logging.getLogger(__name__)

REQUIRED_LABELS = ("entailment", "neutral", "contradiction")


class NLIError(RuntimeError):
    """The NLI model is unavailable, misconfigured or produced invalid output."""


@dataclass(frozen=True)
class NLIScores:
    """Softmax scores for one (premise, hypothesis) pair."""

    entailment: float
    neutral: float
    contradiction: float

    @property
    def best_label(self) -> str:
        return max(
            (("entailment", self.entailment), ("neutral", self.neutral), ("contradiction", self.contradiction)),
            key=lambda item: item[1],
        )[0]

    def to_dict(self) -> dict[str, float]:
        return {
            "entailment_score": round(self.entailment, 6),
            "neutral_score": round(self.neutral, 6),
            "contradiction_score": round(self.contradiction, 6),
        }


def _repo_dirname(model_name: str) -> str:
    return "models--" + model_name.replace("/", "--")


def resolve_local_snapshot(model_name: str, cache_dir: Path) -> Path:
    """Find the cached snapshot directory for ``model_name`` without network access.

    Hugging Face stores repositories either directly under the cache root or
    under a ``hub/`` sub-directory (``HF_HOME`` layout); both are checked.
    """
    base = _repo_dirname(model_name)
    candidates: list[Path] = []
    for root in (Path(cache_dir), Path(cache_dir) / "hub"):
        snapshots = root / base / "snapshots"
        if not snapshots.is_dir():
            continue
        for entry in snapshots.iterdir():
            if entry.is_dir() and (entry / "config.json").is_file():
                candidates.append(entry)
    if not candidates:
        raise NLIError(
            f"NLI model '{model_name}' is not present in the local cache at "
            f"{cache_dir}. No download was attempted."
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


class NLIService:
    """Lazy, thread-safe wrapper around a Sentence Transformers CrossEncoder."""

    def __init__(
        self,
        model_name: str,
        cache_dir: Path,
        *,
        batch_size: int = 8,
        device: str = "cpu",
        max_length: int = 512,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = Path(cache_dir)
        self._batch_size = batch_size
        self._device = device
        self._max_length = max_length
        self._model: object | None = None
        self._label_index: dict[str, int] | None = None
        self._model_path: Path | None = None
        self._lock = threading.Lock()

    # -- introspection -------------------------------------------------

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def batch_size(self) -> int:
        return self._batch_size

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def model_path(self) -> Path | None:
        return self._model_path

    @property
    def label_index(self) -> dict[str, int]:
        """Mapping ``{"contradiction": i, "entailment": j, "neutral": k}``."""
        self.ensure_loaded()
        assert self._label_index is not None
        return dict(self._label_index)

    def label_for(self, index: int) -> str:
        mapping = self.label_index
        for label, position in mapping.items():
            if position == index:
                return label
        raise NLIError(f"The model has no label at index {index}.")

    # -- loading -------------------------------------------------------

    def _read_label_mapping(self, model: object) -> dict[str, int]:
        config = getattr(getattr(model, "model", None), "config", None)
        raw = getattr(config, "id2label", None)
        if not isinstance(raw, dict) or not raw:
            raise NLIError(
                "The NLI model did not expose an id2label mapping; refusing to "
                "guess which output class is entailment."
            )
        mapping: dict[str, int] = {}
        for key, value in raw.items():
            try:
                index = int(key)
            except (TypeError, ValueError) as exc:
                raise NLIError("The NLI model has a non-numeric label id.") from exc
            label = str(value).strip().lower()
            if label not in REQUIRED_LABELS:
                raise NLIError(
                    f"Unexpected NLI label '{value}'. Expected exactly "
                    f"{sorted(REQUIRED_LABELS)}."
                )
            if label in mapping:
                raise NLIError(f"Duplicate NLI label '{label}' in the model config.")
            mapping[label] = index

        if set(mapping) != set(REQUIRED_LABELS):
            raise NLIError(
                "The NLI model label mapping is incomplete: "
                f"{sorted(mapping)} (expected {sorted(REQUIRED_LABELS)})."
            )
        if sorted(mapping.values()) != list(range(len(mapping))):
            raise NLIError(
                f"The NLI label indices {sorted(mapping.values())} are not 0..{len(mapping) - 1}."
            )
        return mapping

    def ensure_loaded(self) -> object:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:  # pragma: no cover - pinned dependency
                raise NLIError("sentence-transformers is not installed.") from exc

            snapshot = resolve_local_snapshot(self._model_name, self._cache_dir)
            try:
                model = CrossEncoder(
                    str(snapshot),
                    device=self._device,
                    local_files_only=True,
                    max_length=self._max_length,
                )
            except Exception as exc:  # noqa: BLE001 - surfaced as a typed error
                raise NLIError(
                    f"The NLI model at {snapshot} could not be loaded."
                ) from exc

            mapping = self._read_label_mapping(model)
            self._model = model
            self._label_index = mapping
            self._model_path = snapshot
            logger.info(
                "Loaded NLI model %s from %s (labels: %s)",
                self._model_name,
                snapshot,
                mapping,
            )
        return self._model

    # -- inference -----------------------------------------------------

    def score_pairs(self, pairs: list[tuple[str, str]]) -> list[NLIScores]:
        """Score (premise, hypothesis) pairs; empty input returns an empty list."""
        if not pairs:
            return []
        prepared: list[tuple[str, str]] = []
        for premise, hypothesis in pairs:
            if not isinstance(premise, str) or not premise.strip():
                raise ValueError("NLI premise must not be empty.")
            if not isinstance(hypothesis, str) or not hypothesis.strip():
                raise ValueError("NLI hypothesis must not be empty.")
            prepared.append((premise.strip(), hypothesis.strip()))

        model = self.ensure_loaded()
        mapping = self.label_index
        try:
            scores = model.predict(  # type: ignore[attr-defined]
                prepared,
                batch_size=self._batch_size,
                apply_softmax=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as exc:  # noqa: BLE001 - typed for the caller
            raise NLIError("NLI inference failed.") from exc

        matrix = np.asarray(scores, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape != (len(prepared), len(mapping)):
            raise NLIError(
                f"NLI output had shape {matrix.shape}, expected "
                f"({len(prepared)}, {len(mapping)})."
            )
        if not np.all(np.isfinite(matrix)):
            raise NLIError("NLI output contained non-finite scores.")

        results: list[NLIScores] = []
        for row in matrix:
            results.append(
                NLIScores(
                    entailment=float(row[mapping["entailment"]]),
                    neutral=float(row[mapping["neutral"]]),
                    contradiction=float(row[mapping["contradiction"]]),
                )
            )
        return results


_service: NLIService | None = None
_service_lock = threading.Lock()


def get_nli_service() -> NLIService:
    """Process-wide NLI service (loads on first use, ~1 s from cache)."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                settings = get_settings()
                _service = NLIService(
                    settings.nli_model,
                    settings.model_cache_dir,
                    batch_size=settings.nli_batch_size,
                )
    return _service


def reset_nli_service() -> None:
    """Forget the cached service (tests)."""
    global _service
    with _service_lock:
        _service = None


__all__ = [
    "NLIError",
    "NLIScores",
    "NLIService",
    "REQUIRED_LABELS",
    "get_nli_service",
    "reset_nli_service",
    "resolve_local_snapshot",
]
