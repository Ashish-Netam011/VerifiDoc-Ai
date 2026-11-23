"""Asynchronous OpenRouter chat-completions client."""

from __future__ import annotations

import logging

import httpx

from app.services.llm_provider import (
    BaseLLMProvider,
    LLMAuthenticationError,
    LLMCreditsError,
    LLMError,
    LLMResponseError,
    LLMStatus,
    LLMTimeoutError,
    LLMUnavailableError,
)

logger = logging.getLogger(__name__)
AVAILABILITY_TIMEOUT_S = 5.0
GENERATION_OPTIONS = {"temperature": 0.2, "top_p": 0.9}


class OpenRouterProvider(BaseLLMProvider):
    """Thin async wrapper around OpenRouter's OpenAI-compatible API."""

    name = "openrouter"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        timeout_s: float,
        *,
        max_tokens: int = 1024,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._max_tokens = max_tokens
        self._client: httpx.AsyncClient | None = None

    @property
    def model(self) -> str:
        return self._model

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout_s, connect=5.0),
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def check_availability(self) -> LLMStatus:
        if not self._api_key:
            return LLMStatus(
                available=False,
                model=self._model,
                model_present=False,
                detail="OPENROUTER_API_KEY is not configured.",
                failure_kind="missing_credentials",
            )

        client = self._get_client()
        try:
            auth_response = await client.get(
                "/auth/key", timeout=AVAILABILITY_TIMEOUT_S
            )
            if auth_response.status_code in (
                httpx.codes.UNAUTHORIZED,
                httpx.codes.FORBIDDEN,
            ):
                return LLMStatus(
                    available=False,
                    model=self._model,
                    model_present=False,
                    detail="OpenRouter rejected the configured API key.",
                    failure_kind="authentication",
                )
            if auth_response.status_code != httpx.codes.OK:
                return LLMStatus(
                    available=False,
                    model=self._model,
                    model_present=False,
                    detail=f"OpenRouter answered with HTTP {auth_response.status_code}.",
                    failure_kind="unavailable",
                )

            model_response = await client.get(
                "/models", timeout=AVAILABILITY_TIMEOUT_S
            )
            if model_response.status_code != httpx.codes.OK:
                return LLMStatus(
                    available=False,
                    model=self._model,
                    model_present=False,
                    detail=(
                        "OpenRouter model catalogue returned HTTP "
                        f"{model_response.status_code}."
                    ),
                    failure_kind="unavailable",
                )
            payload = model_response.json()
            models = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(models, list):
                return LLMStatus(
                    available=False,
                    model=self._model,
                    model_present=False,
                    detail="OpenRouter returned an invalid model catalogue.",
                    failure_kind="invalid_response",
                )
            model_present = any(
                isinstance(entry, dict) and entry.get("id") == self._model
                for entry in models
            )
            if not model_present:
                detail = f"Model '{self._model}' is not listed by OpenRouter."
                failure_kind = "configuration"
            else:
                detail = "OpenRouter credentials and configured model are available."
                failure_kind = None
            return LLMStatus(
                available=model_present,
                model=self._model,
                model_present=model_present,
                detail=detail,
                failure_kind=failure_kind,
            )
        except httpx.TimeoutException:
            return LLMStatus(
                available=False,
                model=self._model,
                model_present=False,
                detail=f"OpenRouter did not respond within {AVAILABILITY_TIMEOUT_S:g}s.",
                failure_kind="unavailable",
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("OpenRouter availability probe failed: %s", exc)
            return LLMStatus(
                available=False,
                model=self._model,
                model_present=False,
                detail="OpenRouter is not reachable or returned an invalid response.",
                failure_kind="unavailable",
            )

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        response_format: str | None = None,
    ) -> str:
        if not self._api_key:
            raise LLMUnavailableError(
                "OpenRouter API key is not configured. Set OPENROUTER_API_KEY."
            )

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, object] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "max_tokens": self._max_tokens,
            **GENERATION_OPTIONS,
        }
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        try:
            response = await self._get_client().post(
                "/chat/completions", json=payload
            )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"OpenRouter did not respond within {self._timeout_s:g}s."
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("OpenRouter request failed: %s", exc)
            raise LLMUnavailableError("OpenRouter is not reachable.") from exc

        if response.status_code in (
            httpx.codes.UNAUTHORIZED,
            httpx.codes.FORBIDDEN,
        ):
            raise LLMAuthenticationError(
                "OpenRouter rejected the API key. Check OPENROUTER_API_KEY."
            )
        if response.status_code == httpx.codes.NOT_FOUND:
            raise LLMError(
                f"Model '{self._model}' is unavailable on OpenRouter."
            )
        if response.status_code == httpx.codes.PAYMENT_REQUIRED:
            raise LLMCreditsError(
                "OpenRouter account has insufficient credits."
            )
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raise LLMUnavailableError("OpenRouter rate limit was reached.")
        if response.status_code >= 500:
            raise LLMUnavailableError(
                f"OpenRouter service returned HTTP {response.status_code}."
            )
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise LLMError(f"OpenRouter returned HTTP {response.status_code}.")

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMResponseError(
                "OpenRouter returned a malformed response body."
            ) from exc

        choices = data.get("choices") if isinstance(data, dict) else None
        message = None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("OpenRouter returned an empty completion.")
        return content.strip()
