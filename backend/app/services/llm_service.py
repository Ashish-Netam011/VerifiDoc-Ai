"""Primary OpenRouter generation with a bounded local Ollama fallback."""

from __future__ import annotations

import logging
import threading
import time
from contextvars import ContextVar

from app.config import get_settings
from app.services.llm_provider import (
    BaseLLMProvider,
    LLMAuthenticationError,
    LLMError,
    LLMFallbackError,
    LLMResponseError,
    LLMStatus,
)
from app.services.ollama_service import OllamaProvider
from app.services.openrouter_service import OpenRouterProvider

logger = logging.getLogger(__name__)


class HybridLLMService:
    """Runs the configured provider and falls back once when policy allows."""

    def __init__(
        self,
        openrouter: BaseLLMProvider,
        ollama: BaseLLMProvider,
        *,
        provider_mode: str = "hybrid",
        fallback_enabled: bool = True,
        fallback_on_auth_error: bool = False,
    ) -> None:
        self._openrouter = openrouter
        self._ollama = ollama
        self._provider_mode = provider_mode
        self._fallback_enabled = fallback_enabled
        self._fallback_on_auth_error = fallback_on_auth_error
        self._last_provider: ContextVar[BaseLLMProvider | None] = ContextVar(
            "llm_last_provider", default=None
        )

    @property
    def model(self) -> str:
        provider = self._last_provider.get()
        if provider is not None:
            return provider.model
        return (
            self._ollama.model
            if self._provider_mode == "ollama"
            else self._openrouter.model
        )

    @property
    def last_provider(self) -> str | None:
        provider = self._last_provider.get()
        return provider.name if provider is not None else None

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        response_format: str | None = None,
    ) -> str:
        started = time.perf_counter()
        if self._provider_mode == "ollama":
            result = await self._generate_with(self._ollama, prompt, system, response_format)
            self._last_provider.set(self._ollama)
            self._log_final(self._ollama, started)
            return result

        try:
            result = await self._generate_with(
                self._openrouter, prompt, system, response_format
            )
        except LLMError as primary_error:
            if not self._should_fallback(primary_error):
                logger.warning(
                    "LLM primary failed provider=%s error=%s fallback=disabled",
                    self._openrouter.name,
                    type(primary_error).__name__,
                )
                raise

            logger.warning(
                "LLM fallback reason provider=%s error=%s",
                self._openrouter.name,
                type(primary_error).__name__,
            )
            try:
                result = await self._generate_with(
                    self._ollama, prompt, system, response_format
                )
            except LLMError as fallback_error:
                logger.error(
                    "LLM fallback failed provider=%s error=%s",
                    self._ollama.name,
                    type(fallback_error).__name__,
                )
                raise LLMFallbackError(
                    primary_error, fallback_error
                ) from fallback_error
            self._last_provider.set(self._ollama)
            self._log_final(self._ollama, started)
            return result

        self._last_provider.set(self._openrouter)
        self._log_final(self._openrouter, started)
        return result

    async def _generate_with(
        self,
        provider: BaseLLMProvider,
        prompt: str,
        system: str | None,
        response_format: str | None,
    ) -> str:
        started = time.perf_counter()
        logger.info("LLM request started provider=%s", provider.name)
        result = await provider.generate(
            prompt,
            system=system,
            response_format=response_format,
        )
        if not isinstance(result, str) or not result.strip():
            raise LLMResponseError(
                f"{provider.name} returned an empty completion."
            )
        logger.info(
            "LLM response received provider=%s duration_ms=%.1f",
            provider.name,
            (time.perf_counter() - started) * 1000,
        )
        return result.strip()

    def _should_fallback(self, error: LLMError) -> bool:
        if self._provider_mode != "hybrid" or not self._fallback_enabled:
            return False
        if isinstance(error, LLMAuthenticationError):
            return self._fallback_on_auth_error
        return bool(getattr(error, "recoverable", False))

    @staticmethod
    def _log_final(provider: BaseLLMProvider, started: float) -> None:
        logger.info(
            "LLM generation complete provider=%s model=%s total_duration_ms=%.1f",
            provider.name,
            provider.model,
            (time.perf_counter() - started) * 1000,
        )

    async def check_availability(self) -> LLMStatus:
        if self._provider_mode == "ollama":
            return await self._ollama.check_availability()

        primary_status = await self._openrouter.check_availability()
        if primary_status.available or not self._should_fallback_for_status(
            primary_status
        ):
            return primary_status

        fallback_status = await self._ollama.check_availability()
        if fallback_status.available:
            return LLMStatus(
                available=True,
                model=fallback_status.model,
                model_present=True,
                detail=(
                    f"OpenRouter unavailable; Ollama fallback is ready. "
                    f"{primary_status.detail}"
                ),
            )
        return LLMStatus(
            available=False,
            model=primary_status.model,
            model_present=primary_status.model_present,
            detail=(
                f"{primary_status.detail} Ollama fallback unavailable: "
                f"{fallback_status.detail}"
            ),
            failure_kind=primary_status.failure_kind,
        )

    def _should_fallback_for_status(self, status: LLMStatus) -> bool:
        if self._provider_mode != "hybrid" or not self._fallback_enabled:
            return False
        if status.failure_kind == "authentication":
            return self._fallback_on_auth_error
        return status.failure_kind in {
            "unavailable",
            "invalid_response",
            "missing_credentials",
        }

    async def aclose(self) -> None:
        await self._openrouter.aclose()
        await self._ollama.aclose()


_service: HybridLLMService | None = None
_service_lock = threading.Lock()


def get_llm_service() -> HybridLLMService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                settings = get_settings()
                _service = HybridLLMService(
                    OpenRouterProvider(
                        base_url=settings.openrouter_base_url,
                        model=settings.openrouter_model,
                        api_key=settings.openrouter_api_key,
                        timeout_s=settings.llm_timeout_s,
                        max_tokens=settings.llm_num_predict,
                    ),
                    OllamaProvider(
                        base_url=settings.ollama_base_url,
                        model=settings.ollama_model,
                        timeout_s=settings.llm_timeout_s,
                        num_ctx=settings.llm_num_ctx,
                        num_predict=settings.llm_num_predict,
                    ),
                    provider_mode=settings.llm_provider,
                    fallback_enabled=settings.llm_fallback_enabled,
                    fallback_on_auth_error=settings.llm_fallback_on_auth_error,
                )
    return _service


async def shutdown_llm_service() -> None:
    global _service
    if _service is not None:
        await _service.aclose()
        _service = None
