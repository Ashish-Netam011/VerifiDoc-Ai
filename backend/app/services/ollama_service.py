"""Asynchronous client for a locally running Ollama instance."""

from __future__ import annotations

import logging

import httpx

from app.services.llm_provider import (
    BaseLLMProvider,
    LLMError,
    LLMResponseError,
    LLMStatus,
    LLMTimeoutError,
    LLMUnavailableError,
)

logger = logging.getLogger(__name__)
AVAILABILITY_TIMEOUT_S = 3.0
GENERATION_OPTIONS = {"temperature": 0.2, "top_p": 0.9}


class OllamaProvider(BaseLLMProvider):
    """Local Ollama provider using the same prompt and generation contract."""

    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float,
        *,
        num_ctx: int = 8192,
        num_predict: int = 1024,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s
        self._num_ctx = num_ctx
        self._num_predict = num_predict
        self._client: httpx.AsyncClient | None = None

    @property
    def model(self) -> str:
        return self._model

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout_s, connect=5.0),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def check_availability(self) -> LLMStatus:
        client = self._get_client()
        try:
            response = await client.get(
                "/api/tags", timeout=AVAILABILITY_TIMEOUT_S
            )
        except httpx.TimeoutException:
            return LLMStatus(
                False,
                self._model,
                False,
                f"Ollama did not respond within {AVAILABILITY_TIMEOUT_S:g}s.",
                "unavailable",
            )
        except httpx.HTTPError as exc:
            logger.debug("Ollama availability probe failed: %s", exc)
            return LLMStatus(
                False,
                self._model,
                False,
                f"Ollama is not reachable at {self._base_url}.",
                "unavailable",
            )

        if response.status_code != httpx.codes.OK:
            return LLMStatus(
                False,
                self._model,
                False,
                f"Ollama answered with HTTP {response.status_code}.",
                "unavailable",
            )
        try:
            payload = response.json()
        except ValueError:
            return LLMStatus(
                False,
                self._model,
                False,
                "Ollama returned a malformed model list.",
                "invalid_response",
            )

        models = payload.get("models", []) if isinstance(payload, dict) else []
        installed = {
            str(entry.get("name") or entry.get("model") or "")
            for entry in models
            if isinstance(entry, dict)
        }
        present = self._model in installed
        detail = (
            "Ollama is running and the configured model is installed."
            if present
            else f"Ollama is running but model '{self._model}' is not installed."
        )
        return LLMStatus(
            available=present,
            model=self._model,
            model_present=present,
            detail=detail,
            failure_kind=None if present else "configuration",
        )

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        response_format: str | None = None,
    ) -> str:
        payload: dict[str, object] = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            # Answers are JSON-constrained; hidden reasoning tokens only consume
            # the request timeout on thinking-capable models.
            "think": False,
            "options": {
                **GENERATION_OPTIONS,
                "num_ctx": self._num_ctx,
                "num_predict": self._num_predict,
            },
        }
        if system:
            payload["system"] = system
        if response_format == "json":
            payload["format"] = "json"

        try:
            response = await self._get_client().post(
                "/api/generate", json=payload
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"Ollama did not respond within {self._timeout_s:g}s."
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("Ollama request failed: %s", type(exc).__name__)
            raise LLMUnavailableError("Ollama is not reachable.") from exc

        if response.status_code == httpx.codes.NOT_FOUND:
            raise LLMUnavailableError(
                f"Model '{self._model}' is not available in Ollama."
            )
        if response.status_code >= 500:
            raise LLMUnavailableError(
                f"Ollama service returned HTTP {response.status_code}."
            )
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise LLMError(f"Ollama returned HTTP {response.status_code}.")

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMResponseError(
                "Ollama returned a malformed response body."
            ) from exc

        text = data.get("response") if isinstance(data, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise LLMResponseError("Ollama returned an empty completion.")
        return text.strip()
