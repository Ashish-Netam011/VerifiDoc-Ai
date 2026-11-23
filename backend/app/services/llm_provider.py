"""Shared contracts and errors for language-model providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LLMError(RuntimeError):
    """Base error for language-model failures surfaced to the API layer."""


class LLMUnavailableError(LLMError):
    """A provider is temporarily unreachable or rate limited."""

    recoverable = True


class LLMTimeoutError(LLMError):
    """A provider request exceeded its bounded timeout."""

    recoverable = True


class LLMResponseError(LLMError):
    """A provider returned a malformed or incomplete completion."""

    recoverable = True


class LLMCreditsError(LLMUnavailableError):
    """The account behind a hosted provider cannot pay for the request.

    This is a billing state, not a credential or transport failure, so the
    hybrid service treats it as recoverable and uses the local fallback.
    """

    recoverable = True


class LLMAuthenticationError(LLMUnavailableError):
    """Provider credentials were rejected; fallback is policy-controlled."""

    recoverable = False


class LLMFallbackError(LLMError):
    """Both the primary provider and its configured fallback failed."""

    def __init__(self, primary_error: Exception, fallback_error: Exception) -> None:
        self.primary_error = primary_error
        self.fallback_error = fallback_error
        super().__init__(
            "Primary LLM provider failed with "
            f"{type(primary_error).__name__}; fallback failed with "
            f"{type(fallback_error).__name__}."
        )


@dataclass(frozen=True)
class LLMStatus:
    available: bool
    model: str
    model_present: bool
    detail: str
    failure_kind: str | None = None


class BaseLLMProvider(Protocol):
    """Provider interface used by the hybrid generation service."""

    name: str

    @property
    def model(self) -> str: ...

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        response_format: str | None = None,
    ) -> str: ...

    async def check_availability(self) -> LLMStatus: ...

    async def aclose(self) -> None: ...
