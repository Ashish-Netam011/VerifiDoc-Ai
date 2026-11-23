"""Health endpoint: backend liveness and LLM availability, reported separately."""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.llm_service import get_llm_service

APP_VERSION = "0.2.0"

# Monotonic start time, used to report uptime without wall-clock changes.
_STARTED_AT = time.monotonic()

router = APIRouter(prefix="/api", tags=["health"])


class BackendHealth(BaseModel):
    status: Literal["ok"] = Field(description="The API process itself is serving.")
    version: str = Field(description="Backend version.")
    uptime_s: float = Field(description="Seconds since the API process started.")


class LLMHealth(BaseModel):
    available: bool = Field(description="A configured LLM provider is usable.")
    model: str = Field(description="Model the backend is configured to use.")
    model_present: bool = Field(
        description="The configured model is available from its provider."
    )
    detail: str = Field(description="Human-readable explanation of the state.")


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = Field(
        description="'degraded' means the API is up but the LLM is not usable."
    )
    backend: BackendHealth
    llm: LLMHealth


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Backend and LLM health",
    description=(
        "Reports API liveness separately from configured LLM provider availability."
    ),
)
async def health() -> HealthResponse:
    status = await get_llm_service().check_availability()

    llm = LLMHealth(
        available=status.available and status.model_present,
        model=status.model,
        model_present=status.model_present,
        detail=status.detail,
    )
    return HealthResponse(
        status="ok" if llm.available else "degraded",
        backend=BackendHealth(
            status="ok",
            version=APP_VERSION,
            uptime_s=round(time.monotonic() - _STARTED_AT, 3),
        ),
        llm=llm,
    )
