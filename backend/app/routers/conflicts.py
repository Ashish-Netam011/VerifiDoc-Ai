"""Conservative cross-document fact comparison endpoint."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.services.contradiction_service import analyze_retrieval
from app.services.document_store import DocumentStore, DocumentStoreError
from app.services.embedding_service import EmbeddingModelError
from app.services.retrieval_service import get_retrieval_service
from app.services.reranker_service import RerankerError
from app.services.vector_store import VectorStoreError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["conflicts"])


class ConflictAnalysisRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=20, ge=2, le=50)
    document_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be empty or whitespace only")
        return value


class ConflictAnalysisResponse(BaseModel):
    query: str
    result_count: int
    facts: list[dict[str, Any]]
    comparisons: list[dict[str, Any]]


@router.post(
    "/conflicts",
    response_model=ConflictAnalysisResponse,
    summary="Compare explicit facts across retrieved documents",
    description=(
        "Compares only explicit numeric/date statements with matching subject "
        "and attribute. Context mismatches and incomplete provenance remain "
        "unresolved; this heuristic does not determine legal applicability."
    ),
)
async def analyze_conflicts(payload: ConflictAnalysisRequest) -> ConflictAnalysisResponse:
    settings = get_settings()
    store = DocumentStore(settings.data_dir)
    if payload.document_id is not None and store.get_document(payload.document_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    try:
        results = await asyncio.to_thread(
            get_retrieval_service().search,
            payload.query,
            top_k=payload.top_k,
            document_id=payload.document_id,
        )
    except EmbeddingModelError as exc:
        logger.error("Conflict analysis retrieval failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Semantic search is unavailable. {exc}",
        ) from exc
    except RerankerError as exc:
        logger.error("Conflict analysis reranker unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Relevance reranking is unavailable. {exc}",
        ) from exc
    except VectorStoreError as exc:
        logger.error("Conflict analysis vector search failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The vector index could not be searched.",
        ) from exc
    except DocumentStoreError as exc:
        logger.error("Conflict analysis chunk lookup failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The stored chunks could not be read.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    analysis = analyze_retrieval(results)
    return ConflictAnalysisResponse(
        query=payload.query,
        result_count=len(results),
        facts=analysis["facts"],
        comparisons=analysis["comparisons"],
    )
