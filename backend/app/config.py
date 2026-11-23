"""Centralised, validated configuration for the ProofLens AI backend.

All values come from environment variables (loaded from ``backend/.env`` when
present). Relative paths in the environment file are resolved against the
backend directory, never against the process working directory, so the API
behaves the same whether it is started from ``backend/`` or from the repo root.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

# ``backend/`` - the directory that contains ``app/``, ``.env`` and ``.venv``.
BACKEND_DIR = Path(__file__).resolve().parent.parent

# Load .env without overriding variables already set in the real environment.
load_dotenv(BACKEND_DIR / ".env", override=False)

DEFAULT_CORS_ORIGINS = ("http://localhost:5173",)


def _env(name: str, default: str) -> str:
    """Return a stripped environment value, falling back to ``default``."""
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    return raw or default


class Settings(BaseModel):
    """Validated runtime settings for the backend."""

    ollama_url: str = Field(default="http://localhost:11434")
    llm_model: str = Field(default="qwen2.5:3b-instruct")
    llm_timeout_s: float = Field(default=45.0, gt=0, le=600)
    data_dir: Path = Field(default=BACKEND_DIR / ".." / "data")
    max_upload_mb: int = Field(default=25, ge=1, le=1024)
    top_k: int = Field(default=6, ge=1, le=50)
    # Page-aware chunking. Chunks never span pages; these two values control
    # window size and character overlap inside a single page.
    chunk_size: int = Field(default=800, ge=100, le=10_000)
    chunk_overlap: int = Field(default=120, ge=0, le=5_000)
    # Embeddings: cached Sentence Transformers model, CPU inference by default.
    embed_model: str = Field(default="intfloat/multilingual-e5-small")
    embed_dim: int = Field(default=384, ge=1, le=4096)
    embed_batch_size: int = Field(default=16, ge=1, le=256)
    # Reciprocal Rank Fusion constant (the "k" in 1 / (k + rank)).
    rrf_k: int = Field(default=60, ge=1, le=1000)
    # Evidence-grounded answering.
    qa_top_k: int = Field(default=5, ge=1, le=20)
    qa_max_context_chars: int = Field(default=6000, ge=500, le=40_000)
    # Citation verification (NLI). Thresholds are on the model's softmax
    # outputs, not calibrated probabilities - see the Phase 3.2 report.
    nli_model: str = Field(default="cross-encoder/nli-deberta-base")
    nli_batch_size: int = Field(default=8, ge=1, le=64)
    nli_entailment_threshold: float = Field(default=0.60, gt=0.0, lt=1.0)
    nli_contradiction_threshold: float = Field(default=0.60, gt=0.0, lt=1.0)
    # Evidence sufficiency / abstention. Thresholds are operating points chosen
    # from observed behaviour, not calibrated probabilities - see Phase 3.3.
    evidence_min_relevant_chunks: int = Field(default=1, ge=1, le=50)
    evidence_min_semantic_score: float = Field(default=0.70, gt=0.0, lt=1.0)
    evidence_max_items: int = Field(default=8, ge=1, le=50)
    evidence_require_verification: bool = Field(default=True)
    evidence_conservative_mode: bool = Field(default=False)
    model_cache_dir: Path = Field(default=BACKEND_DIR / ".." / "data" / "models_cache")
    cors_origins: list[str] = Field(
        default_factory=lambda: list(DEFAULT_CORS_ORIGINS)
    )

    @field_validator("ollama_url")
    @classmethod
    def _validate_ollama_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("OLLAMA_URL must start with http:// or https://")
        return value

    @field_validator("llm_model")
    @classmethod
    def _validate_llm_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("LLM_MODEL must not be empty")
        return value

    @field_validator("embed_model")
    @classmethod
    def _validate_embed_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("EMBED_MODEL must not be empty")
        return value

    @field_validator("data_dir", "model_cache_dir", mode="after")
    @classmethod
    def _resolve_paths(cls, value: Path) -> Path:
        value = value.expanduser()
        if not value.is_absolute():
            value = BACKEND_DIR / value
        return value.resolve()

    @model_validator(mode="after")
    def _validate_chunking(self) -> "Settings":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        return self

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            parsed = [origin.strip().rstrip("/") for origin in value.split(",")]
            parsed = [origin for origin in parsed if origin]
            if not parsed:
                raise ValueError("CORS_ORIGINS must contain at least one origin")
            return parsed
        return value


def _load_settings() -> Settings:
    cors_raw = _env("CORS_ORIGINS", ",".join(DEFAULT_CORS_ORIGINS))
    return Settings(
        ollama_url=_env("OLLAMA_URL", "http://localhost:11434"),
        llm_model=_env("LLM_MODEL", "qwen2.5:3b-instruct"),
        llm_timeout_s=_env("LLM_TIMEOUT_S", "45"),
        data_dir=Path(_env("DATA_DIR", str(BACKEND_DIR / ".." / "data"))),
        max_upload_mb=_env("MAX_UPLOAD_MB", "25"),
        top_k=_env("TOP_K", "6"),
        chunk_size=_env("CHUNK_SIZE", "800"),
        chunk_overlap=_env("CHUNK_OVERLAP", "120"),
        embed_model=_env("EMBED_MODEL", "intfloat/multilingual-e5-small"),
        embed_dim=_env("EMBED_DIM", "384"),
        embed_batch_size=_env("EMBED_BATCH_SIZE", "16"),
        rrf_k=_env("RRF_K", "60"),
        qa_top_k=_env("QA_TOP_K", "5"),
        qa_max_context_chars=_env("QA_MAX_CONTEXT_CHARS", "6000"),
        nli_model=_env("NLI_MODEL", "cross-encoder/nli-deberta-base"),
        nli_batch_size=_env("NLI_BATCH_SIZE", "8"),
        nli_entailment_threshold=_env("NLI_ENTAILMENT_THRESHOLD", "0.60"),
        nli_contradiction_threshold=_env("NLI_CONTRADICTION_THRESHOLD", "0.60"),
        evidence_min_relevant_chunks=_env("EVIDENCE_MIN_RELEVANT_CHUNKS", "1"),
        evidence_min_semantic_score=_env("EVIDENCE_MIN_SEMANTIC_SCORE", "0.70"),
        evidence_max_items=_env("EVIDENCE_MAX_ITEMS", "8"),
        evidence_require_verification=_env("EVIDENCE_REQUIRE_VERIFICATION", "true"),
        evidence_conservative_mode=_env("EVIDENCE_CONSERVATIVE_MODE", "false"),
        model_cache_dir=Path(
            _env("HF_HOME", str(BACKEND_DIR / ".." / "data" / "models_cache"))
        ),
        cors_origins=cors_raw,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings (validated once, then cached)."""
    return _load_settings()


settings = get_settings()
