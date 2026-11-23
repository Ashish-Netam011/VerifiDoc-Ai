"""Temporary LLM integration-test endpoint.

This is NOT the final evidence-grounded answering API - no retrieval, no
citation checks, no verification. It only tests the configured provider flow.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, Field, field_validator

from app.services.llm_service import get_llm_service

MAX_PROMPT_CHARS = 4000

router = APIRouter(prefix="/api", tags=["llm-integration"])


class TestLLMRequest(BaseModel):
    prompt: str = Field(
        min_length=1,
        max_length=MAX_PROMPT_CHARS,
        description="Free-text prompt sent to the configured LLM provider.",
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
    summary="Generate a completion with the configured LLM provider",
    description=(
        "Integration smoke test for the configured LLM provider. Uses "
        "OpenRouter first in hybrid mode and may fall back to Ollama."
    ),
)
async def test_llm(payload: TestLLMRequest) -> TestLLMResponse:
    service = get_llm_service()
    text = await service.generate(payload.prompt)
    return TestLLMResponse(
        response=text,
        model=service.model,
        success=True,
    )
