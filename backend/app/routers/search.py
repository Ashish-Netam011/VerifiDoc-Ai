"""Hybrid retrieval endpoint: semantic + BM25 fusion."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.services.document_store import DocumentStore, DocumentStoreError
from app.services.embedding_service import EmbeddingModelError
from app.services.retrieval_service import get_retrieval_service
from app.services.reranker_service import RerankerError
from app.services.vector_store import VectorStoreError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["retrieval"])

DOCUMENT_ID_PATTERN = r"^[0-9a-f]{32}$"
MAX_TOP_K = 50
MAX_QUERY_CHARS = 1000


class SearchRequest(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=MAX_QUERY_CHARS,
        description="Natural-language question or exact phrase / clause number.",
        examples=["What is the monthly rent payment?"],
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=MAX_TOP_K,
        description=f"Number of fused results to return (1-{MAX_TOP_K}).",
    )
    document_id: str | None = Field(
        default=None,
        pattern=DOCUMENT_ID_PATTERN,
        description="Restrict retrieval to one document.",
    )

    @field_validator("query")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be empty or whitespace only")
        return value


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    filename: str
    page_number: int = Field(ge=0, description="1-indexed page the chunk came from.")
    text: str
    semantic_score: float | None = Field(
        default=None, description="Cosine similarity (null when only BM25 matched)."
    )
    bm25_score: float | None = Field(
        default=None, description="BM25 score (null when only semantic matched)."
    )
    rrf_score: float = Field(description="Fused Reciprocal Rank Fusion score.")
    reranker_score: float | None = Field(
        default=None,
        description="Local query-document relevance score after RRF reranking.",
    )


class SearchResponse(BaseModel):
    query: str
    results: list[SearchHit]
    result_count: int


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Hybrid semantic + keyword search",
    description=(
        "Runs semantic retrieval over the vector index and BM25 over the stored "
        "chunks, then fuses both rankings with Reciprocal Rank Fusion "
        "(1 / (k + rank), k from RRF_K), then reranks a bounded candidate pool "
        "with the configured local relevance cross-encoder. Raw cosine, BM25, "
        "RRF, and relevance scores remain separate."
    ),
    responses={
        422: {"description": "Blank query, bad top_k or malformed document_id."},
        404: {"description": "The requested document_id does not exist."},
        503: {"description": "An embedding or relevance model is unavailable."},
    },
)
async def search_documents(payload: SearchRequest) -> SearchResponse:
    settings = get_settings()

    if payload.document_id is not None:
        record = DocumentStore(settings.data_dir).get_document(payload.document_id)
        if record is None:
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
        logger.error("Search embedding failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Semantic search is unavailable. {exc}",
        ) from exc
    except RerankerError as exc:
        logger.error("Search reranker unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Relevance reranking is unavailable. {exc}",
        ) from exc
    except VectorStoreError as exc:
        logger.error("Vector search failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The vector index could not be searched.",
        ) from exc
    except DocumentStoreError as exc:
        logger.error("Chunk lookup failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The stored chunks could not be read.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    hits = [
        SearchHit(
            chunk_id=result.chunk_id,
            document_id=result.document_id,
            filename=result.filename,
            page_number=result.page_number,
            text=result.text,
            semantic_score=(
                round(result.semantic_score, 6)
                if result.semantic_score is not None
                else None
            ),
            bm25_score=(
                round(result.bm25_score, 6)
                if result.bm25_score is not None
                else None
            ),
            rrf_score=round(result.rrf_score, 6),
            reranker_score=(
                round(result.reranker_score, 6)
                if result.reranker_score is not None
                else None
            ),
        )
        for result in results
    ]
    return SearchResponse(
        query=payload.query,
        results=hits,
        result_count=len(hits),
    )
