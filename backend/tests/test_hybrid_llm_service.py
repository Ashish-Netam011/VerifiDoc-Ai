from __future__ import annotations

import asyncio

import pytest

from app.services.llm_provider import (
    LLMAuthenticationError,
    LLMCreditsError,
    LLMFallbackError,
    LLMResponseError,
    LLMStatus,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.services.llm_service import HybridLLMService


class StubProvider:
    def __init__(
        self,
        name: str,
        model: str,
        *outcomes: str | Exception,
        available: bool = True,
    ) -> None:
        self.name = name
        self._model = model
        self.outcomes = list(outcomes)
        self.available = available
        self.calls: list[dict] = []
        self.closed = False

    @property
    def model(self) -> str:
        return self._model

    async def generate(self, prompt, *, system=None, response_format=None):
        self.calls.append(
            {
                "prompt": prompt,
                "system": system,
                "response_format": response_format,
            }
        )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def check_availability(self):
        return LLMStatus(
            self.available,
            self.model,
            self.available,
            f"{self.name} {'available' if self.available else 'unavailable'}",
            None if self.available else "unavailable",
        )

    async def aclose(self):
        self.closed = True


def _hybrid(
    primary_outcomes: tuple[str | Exception, ...],
    fallback_outcomes: tuple[str | Exception, ...] = ("local answer",),
    *,
    fallback_enabled: bool = True,
    fallback_on_auth_error: bool = False,
    provider_mode: str = "hybrid",
) -> tuple[HybridLLMService, StubProvider, StubProvider]:
    primary = StubProvider("openrouter", "anthropic/claude-sonnet-5", *primary_outcomes)
    fallback = StubProvider("ollama", "qwen3.5:2b", *fallback_outcomes)
    service = HybridLLMService(
        primary,
        fallback,
        provider_mode=provider_mode,
        fallback_enabled=fallback_enabled,
        fallback_on_auth_error=fallback_on_auth_error,
    )
    return service, primary, fallback


async def _generate_with_metadata(service, prompt, **kwargs):
    result = await service.generate(prompt, **kwargs)
    return result, service.model, service.last_provider


def test_openrouter_success_does_not_call_ollama():
    service, primary, fallback = _hybrid(("remote answer",))

    result, model, provider = asyncio.run(
        _generate_with_metadata(
            service, "Question", system="Rules", response_format="json"
        )
    )

    assert result == "remote answer"
    assert primary.calls == [
        {
            "prompt": "Question",
            "system": "Rules",
            "response_format": "json",
        }
    ]
    assert fallback.calls == []
    assert model == "anthropic/claude-sonnet-5"
    assert provider == "openrouter"


@pytest.mark.parametrize(
    "failure",
    [
        LLMTimeoutError("timeout"),
        LLMUnavailableError("connection failed"),
        LLMUnavailableError("HTTP 429"),
        LLMUnavailableError("HTTP 500"),
        LLMResponseError("malformed response"),
        LLMCreditsError("insufficient credits"),
    ],
)
def test_recoverable_openrouter_failures_fall_back_once(failure):
    service, primary, fallback = _hybrid((failure,))

    result, model, provider = asyncio.run(
        _generate_with_metadata(
            service, "Q", system="S", response_format="json"
        )
    )

    assert result == "local answer"
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1
    assert fallback.calls[0] == primary.calls[0]
    assert model == "qwen3.5:2b"
    assert provider == "ollama"


def test_fallback_disabled_propagates_primary_error():
    failure = LLMUnavailableError("network unavailable")
    service, primary, fallback = _hybrid(
        (failure,), fallback_enabled=False
    )

    with pytest.raises(LLMUnavailableError) as raised:
        asyncio.run(service.generate("Question"))

    assert raised.value is failure
    assert len(primary.calls) == 1
    assert fallback.calls == []


def test_authentication_fallback_is_disabled_by_default():
    service, primary, fallback = _hybrid(
        (LLMAuthenticationError("invalid key"),)
    )

    with pytest.raises(LLMAuthenticationError):
        asyncio.run(service.generate("Question"))

    assert len(primary.calls) == 1
    assert fallback.calls == []


def test_authentication_fallback_can_be_explicitly_enabled():
    service, primary, fallback = _hybrid(
        (LLMAuthenticationError("invalid key"),),
        fallback_on_auth_error=True,
    )

    assert asyncio.run(service.generate("Question")) == "local answer"
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


def test_nonrecoverable_provider_error_does_not_fall_back():
    service, primary, fallback = _hybrid((RuntimeError("programming error"),))

    with pytest.raises(RuntimeError, match="programming error"):
        asyncio.run(service.generate("Question"))

    assert len(primary.calls) == 1
    assert fallback.calls == []


def test_successful_low_quality_text_is_not_retried():
    service, primary, fallback = _hybrid(("not valid JSON",))

    assert asyncio.run(
        service.generate("Question", response_format="json")
    ) == "not valid JSON"
    assert len(primary.calls) == 1
    assert fallback.calls == []


def test_ollama_only_mode_never_calls_openrouter():
    service, primary, fallback = _hybrid(
        ("remote answer",),
        provider_mode="ollama",
    )

    assert asyncio.run(service.generate("Question")) == "local answer"
    assert primary.calls == []
    assert len(fallback.calls) == 1


def test_openrouter_only_mode_does_not_fall_back():
    failure = LLMUnavailableError("network unavailable")
    service, primary, fallback = _hybrid(
        (failure,), provider_mode="openrouter"
    )

    with pytest.raises(LLMUnavailableError) as raised:
        asyncio.run(service.generate("Question"))

    assert raised.value is failure
    assert len(primary.calls) == 1
    assert fallback.calls == []


def test_both_providers_unavailable_raise_a_bounded_chained_error():
    primary_error = LLMTimeoutError("remote timeout")
    fallback_error = LLMUnavailableError("local service unavailable")
    service, primary, fallback = _hybrid(
        (primary_error,), (fallback_error,)
    )

    with pytest.raises(LLMFallbackError) as raised:
        asyncio.run(service.generate("Question"))

    assert raised.value.primary_error is primary_error
    assert raised.value.fallback_error is fallback_error
    assert raised.value.__cause__ is fallback_error
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


def test_health_reports_ready_fallback_if_primary_is_unavailable():
    primary = StubProvider(
        "openrouter", "anthropic/claude-sonnet-5", available=False
    )
    fallback = StubProvider("ollama", "qwen3.5:2b")
    service = HybridLLMService(primary, fallback)

    status = asyncio.run(service.check_availability())

    assert status.available is True
    assert status.model == "qwen3.5:2b"
    assert "Ollama fallback is ready" in status.detail
