"""VerifiDoc AI FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import amendments, conflicts, documents, health, qa, questions, search
from app.routers.health import APP_VERSION
from app.services.llm_provider import (
    LLMError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.services.llm_service import shutdown_llm_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("verificdoc")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info("VerifiDoc backend %s starting", APP_VERSION)
    logger.info("LLM provider mode: %s", settings.llm_provider)
    logger.info("LLM model: %s", settings.llm_model)
    logger.info("Data directory: %s", settings.data_dir)
    logger.info("CORS origins: %s", ", ".join(settings.cors_origins))
    yield
    await shutdown_llm_service()
    logger.info("VerifiDoc backend stopped")


app = FastAPI(
    title="VerifiDoc AI API",
    version=APP_VERSION,
    summary="Backend for document-grounded claim verification.",
    description=(
        "PDF ingestion with page-aware chunking and embeddings, hybrid "
        "retrieval (semantic + BM25, fused with Reciprocal Rank Fusion) and "
        "evidence-grounded answering with source provenance. Citation "
        "verification and abstention arrive later."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {"name": "health", "description": "Service and LLM availability."},
        {
            "name": "llm-integration",
            "description": "Temporary configured-provider smoke test.",
        },
        {
            "name": "documents",
            "description": "PDF upload, extraction and page-aware chunks.",
        },
        {
            "name": "retrieval",
            "description": "Hybrid semantic + keyword search over indexed chunks.",
        },
        {
            "name": "qa",
            "description": "Evidence-grounded answers with source references.",
        },
        {
            "name": "conflicts",
            "description": "Conservative cross-document fact comparisons.",
        },
        {
            "name": "amendments",
            "description": "Explicit amendment chains and as-of-date resolution.",
        },
        {"name": "meta", "description": "API metadata."},
    ],
)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(questions.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(qa.router)
app.include_router(conflicts.router)
app.include_router(amendments.router)


@app.get("/", tags=["meta"], summary="API root")
async def root() -> dict[str, str]:
    return {
        "name": "VerifiDoc AI API",
        "version": APP_VERSION,
        "docs": "/docs",
        "health": "/api/health",
        "documents": "/api/documents",
        "search": "/api/search",
        "ask": "/api/ask",
    }


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Invalid request payload.",
            # jsonable_encoder converts validator exceptions held in ``ctx``.
            "errors": jsonable_encoder(exc.errors()),
        },
    )


@app.exception_handler(LLMUnavailableError)
async def llm_unavailable_handler(
    _: Request, exc: LLMUnavailableError
) -> JSONResponse:
    logger.warning("LLM unavailable: %s", exc)
    return JSONResponse(
        status_code=503,
        content={
            "success": False,
            "detail": str(exc),
            "model": get_settings().llm_model,
        },
    )


@app.exception_handler(LLMTimeoutError)
async def llm_timeout_handler(
    _: Request, exc: LLMTimeoutError
) -> JSONResponse:
    logger.warning("LLM timeout: %s", exc)
    return JSONResponse(
        status_code=504,
        content={
            "success": False,
            "detail": str(exc),
            "model": get_settings().llm_model,
        },
    )


@app.exception_handler(LLMError)
async def llm_error_handler(_: Request, exc: LLMError) -> JSONResponse:
    logger.warning("LLM request failed: %s", exc)
    return JSONResponse(
        status_code=502,
        content={
            "success": False,
            "detail": str(exc),
            "model": get_settings().llm_model,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    # Log the cause, never echo internals (or configuration) to the client.
    logger.exception("Unhandled error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"success": False, "detail": "Internal server error."},
    )
