"""Pytest fixtures.

``DATA_DIR`` is redirected to a throw-away directory *before* the application is
imported, so the suite never reads or writes the real ``E:\\Desktop\\ProofLens\\data``.
That throw-away directory also lives on E: (``data/tmp``), not in the system temp
folder on C:, and is deleted again when the whole run passes.

The real E5 model is deliberately not loaded for API tests: an autouse fixture
swaps in a deterministic fake embedding service, so ingestion tests stay fast
and offline. Real-model behaviour is covered in ``test_embeddings.py``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Test data stays on the E: drive with the rest of the project artefacts.
TEST_TMP_ROOT = BACKEND_DIR.parent / "data" / "tmp"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="verificdoc_tests_", dir=TEST_TMP_ROOT))
os.environ["DATA_DIR"] = str(TEST_DATA_DIR)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.services.bm25_service import reset_bm25_index  # noqa: E402
from app.services.citation_verifier import (  # noqa: E402
    ClaimVerification,
    VerificationStatus,
)
from app.services.nli_service import reset_nli_service  # noqa: E402
from app.services.retrieval_service import reset_retrieval_service  # noqa: E402
from app.services.vector_store import reset_vector_stores  # noqa: E402

EMBED_DIM = 384


class FakeCitationVerifier:
    """Deterministic verifier so API tests never load the real NLI model."""

    def verify_claims(self, claims, evidence):
        return [
            ClaimVerification(
                status=VerificationStatus.SUPPORTED,
                reason="test_stub",
                entailment_score=0.99,
                neutral_score=0.005,
                contradiction_score=0.005,
            )
            for _ in claims
        ]


class FakeEmbeddingService:
    """Deterministic stand-in: same text always yields the same unit vector."""

    model_name = "fake-embedding-e5-v1"
    expected_dimension = EMBED_DIM

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, EMBED_DIM), dtype=np.float32)
        rows = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            rng = np.random.default_rng(int.from_bytes(digest[:8], "little"))
            vector = rng.normal(size=EMBED_DIM).astype(np.float32)
            rows.append(vector / np.linalg.norm(vector))
        return np.stack(rows)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_passages([text])[0]

    async def aembed_passages(self, texts: list[str]) -> np.ndarray:
        return self.embed_passages(texts)

    async def aembed_query(self, text: str) -> np.ndarray:
        return self.embed_query(text)


class FakeRerankerService:
    """Deterministic relevance ordering for API tests without model weights."""

    model_name = "fake-reranker"

    def score(self, query: str, passages: list[str]) -> list[float]:
        terms = set(query.lower().split())
        return [
            float(len(terms.intersection(set(passage.lower().split()))))
            for passage in passages
        ]


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return TEST_DATA_DIR


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def fake_embeddings(monkeypatch: pytest.MonkeyPatch) -> FakeEmbeddingService:
    """Use the fake model for every test unless the test builds its own service."""
    service = FakeEmbeddingService()
    monkeypatch.setattr(
        "app.routers.documents.get_embedding_service", lambda: service
    )
    monkeypatch.setattr(
        "app.services.retrieval_service.get_embedding_service", lambda: service
    )
    monkeypatch.setattr(
        "app.services.retrieval_service.get_reranker_service",
        lambda: FakeRerankerService(),
    )
    monkeypatch.setattr(
        "app.services.qa_service.get_citation_verifier",
        lambda: FakeCitationVerifier(),
    )
    reset_vector_stores()
    reset_bm25_index()
    reset_retrieval_service()
    reset_nli_service()
    yield service
    reset_retrieval_service()
    reset_bm25_index()
    reset_vector_stores()
    reset_nli_service()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Remove the throw-away data directory after a fully passing run."""
    keep_test_data = os.environ.get("VERIFICDOC_KEEP_TEST_DATA")
    if keep_test_data is None:
        keep_test_data = os.environ.get("PROOFLENS_KEEP_TEST_DATA", "0")
    if exitstatus == 0 and keep_test_data != "1":
        shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)


@pytest.fixture()
def one_mb_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Temporarily shrink MAX_UPLOAD_MB; settings are cached, so clear it."""
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("MAX_UPLOAD_MB", raising=False)
    get_settings.cache_clear()
