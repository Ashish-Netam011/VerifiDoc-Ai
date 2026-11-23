"""Temporary LLM integration-test endpoint.

This is NOT the final evidence-grounded answering API - no retrieval, no
citation checks, no verification. It only proves the backend can drive the
local Qwen model end to end.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.services.ollama_service import get_ollama_service

MAX_PROMPT_CHARS = 4000

router = APIRouter(prefix="/api", tags=["llm-integration"])


class TestLLMRequest(BaseModel):
    prompt: str = Field(
        min_length=1,
        max_length=MAX_PROMPT_CHARS,
        description="Free-text prompt sent to the local model.",
        examples=["Explain the difference between a contradiction and an amendment."],
    )

    @field_validator("prompt")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("prompt must not be empty or whitespace only")
        return value


class TestLLMResponse(BaseModel):
    response: str = Field(description="Model completion text.")
    model: str = Field(description="Model that produced the completion.")
    success: bool = Field(description="The generation completed without error.")


@router.post(
    "/test-llm",
    response_model=TestLLMResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate a completion with the local model",
    description=(
        "Integration smoke test for the Ollama connection. Returns 503 when "
        "Ollama is unreachable or the configured model is missing, and 504 "
        "when generation exceeds LLM_TIMEOUT_S."
    ),
)
async def test_llm(payload: TestLLMRequest) -> TestLLMResponse:
    settings = get_settings()
    text = await get_ollama_service().generate(payload.prompt)
    return TestLLMResponse(
        response=text,
        model=settings.llm_model,
        success=True,
    )
