"""Centralised, validated configuration for the VerifiDoc AI backend.

All values come from environment variables (loaded from ``backend/.env`` when
present). Relative paths in the environment file are resolved against the
backend directory, never against the process working directory, so the API
behaves the same whether it is started from ``backend/`` or from the repo root.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

# ``backend/`` - the directory that contains ``app/``, ``.env`` and ``.venv``.
BACKEND_DIR = Path(__file__).resolve().parent.parent

# Load .env without overriding variables already set in the real environment.
load_dotenv(BACKEND_DIR / ".env", override=False)

# Keep CPU model loads from multiplying native BLAS/OpenMP worker pools. This
# is especially important on Windows laptops with limited free RAM.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

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

    llm_provider: str = Field(default="hybrid")
    openrouter_api_key: str = Field(default="")
    openrouter_model: str = Field(default="google/gemini-3.7-flash")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1")
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model: str = Field(default="qwen3.5:2b")
    llm_timeout_s: float = Field(default=45.0, gt=0, le=600)
    llm_fallback_enabled: bool = Field(default=True)
    llm_fallback_on_auth_error: bool = Field(default=False)
    llm_num_ctx: int = Field(default=8192, ge=2048, le=131072)
    llm_num_predict: int = Field(default=1024, ge=1, le=8192)
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
    reranker_model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2"
    )
    retrieval_candidate_k: int = Field(default=32, ge=1, le=500)
    rerank_candidate_k: int = Field(default=32, ge=1, le=500)
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

    @field_validator("llm_provider")
    @classmethod
    def _validate_llm_provider(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"hybrid", "openrouter", "ollama"}:
            raise ValueError("LLM_PROVIDER must be hybrid, openrouter, or ollama")
        return value

    @field_validator("openrouter_base_url")
    @classmethod
    def _validate_openrouter_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "OPENROUTER_BASE_URL must be an HTTPS URL without credentials, "
                "query parameters, or a fragment"
            )
        return value

    @field_validator("ollama_base_url")
    @classmethod
    def _validate_ollama_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("OLLAMA_BASE_URL must start with http:// or https://")
        return value

    @field_validator("openrouter_model", "ollama_model")
    @classmethod
    def _validate_model_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Configured model IDs must not be empty")
        return value

    @field_validator("embed_model")
    @classmethod
    def _validate_embed_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("EMBED_MODEL must not be empty")
        return value

    @field_validator("reranker_model")
    @classmethod
    def _validate_reranker_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("RERANKER_MODEL must not be empty")
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
        if self.llm_num_predict >= self.llm_num_ctx:
            raise ValueError("LLM_NUM_PREDICT must be smaller than LLM_NUM_CTX")
        return self

    @property
    def llm_model(self) -> str:
        """Return the configured primary model for legacy response fields."""
        return self.ollama_model if self.llm_provider == "ollama" else self.openrouter_model

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
        llm_provider=_env("LLM_PROVIDER", "hybrid"),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
        openrouter_model=_env(
            "OPENROUTER_MODEL",
            _env("LLM_MODEL", "google/gemini-3.7-flash"),
        ),
        openrouter_base_url=_env(
            "OPENROUTER_BASE_URL",
            _env("OPENROUTER_URL", "https://openrouter.ai/api/v1"),
        ),
        ollama_base_url=_env(
            "OLLAMA_BASE_URL",
            _env("OLLAMA_URL", "http://localhost:11434"),
        ),
        ollama_model=_env("OLLAMA_MODEL", "qwen3.5:2b"),
        llm_timeout_s=_env(
            "LLM_TIMEOUT_SECONDS", _env("LLM_TIMEOUT_S", "45")
        ),
        llm_fallback_enabled=_env("LLM_FALLBACK_ENABLED", "true"),
        llm_fallback_on_auth_error=_env(
            "LLM_FALLBACK_ON_AUTH_ERROR", "false"
        ),
        llm_num_ctx=_env("LLM_NUM_CTX", "8192"),
        llm_num_predict=_env("LLM_NUM_PREDICT", "1024"),
        data_dir=Path(_env("DATA_DIR", str(BACKEND_DIR / ".." / "data"))),
        max_upload_mb=_env("MAX_UPLOAD_MB", "25"),
        top_k=_env("TOP_K", "6"),
        chunk_size=_env("CHUNK_SIZE", "800"),
        chunk_overlap=_env("CHUNK_OVERLAP", "120"),
        embed_model=_env("EMBED_MODEL", "intfloat/multilingual-e5-small"),
        embed_dim=_env("EMBED_DIM", "384"),
        embed_batch_size=_env("EMBED_BATCH_SIZE", "16"),
        reranker_model=_env(
            "RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
        ),
        retrieval_candidate_k=_env("RETRIEVAL_CANDIDATE_K", "32"),
        rerank_candidate_k=_env("RERANK_CANDIDATE_K", "32"),
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
