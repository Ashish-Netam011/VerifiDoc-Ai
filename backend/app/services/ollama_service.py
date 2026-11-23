"""Asynchronous client for a locally running Ollama instance.

The backend never downloads, starts or stops Ollama: it only talks to an
already running server over HTTP on the loopback interface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Availability probes must fail fast; they must not inherit the (longer)
# generation timeout or /api/health would hang whenever Ollama is down.
AVAILABILITY_TIMEOUT_S = 3.0

# Generation request tuning. Kept explicit so behaviour is reproducible.
GENERATION_OPTIONS = {"temperature": 0.2, "top_p": 0.9}


class OllamaError(RuntimeError):
    """Base error for LLM failures surfaced to the API layer."""


class OllamaUnavailableError(OllamaError):
    """Ollama is not reachable, or the configured model is not installed."""


class OllamaTimeoutError(OllamaError):
    """Ollama accepted the request but did not answer within the timeout."""


@dataclass(frozen=True)
class OllamaStatus:
    """Result of probing the local Ollama server."""

    available: bool
    model: str
    model_present: bool
    detail: str


class OllamaService:
    """Thin async wrapper around Ollama's HTTP API."""

    def __init__(self, base_url: str, model: str, timeout_s: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s
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
        """Close the underlying connection pool."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def check_availability(self) -> OllamaStatus:
        """Probe ``/api/tags`` and report whether the server and model are up."""
        client = self._get_client()
        try:
            response = await client.get("/api/tags", timeout=AVAILABILITY_TIMEOUT_S)
        except httpx.TimeoutException:
            return OllamaStatus(
                available=False,
                model=self._model,
                model_present=False,
                detail=f"Ollama did not respond within {AVAILABILITY_TIMEOUT_S:g}s.",
            )
        except httpx.HTTPError as exc:
            logger.debug("Ollama availability probe failed: %s", exc)
            return OllamaStatus(
                available=False,
                model=self._model,
                model_present=False,
                detail=f"Ollama is not reachable at {self._base_url}.",
            )

        if response.status_code != httpx.codes.OK:
            return OllamaStatus(
                available=False,
                model=self._model,
                model_present=False,
                detail=f"Ollama answered with HTTP {response.status_code}.",
            )

        try:
            payload = response.json()
        except ValueError:
            return OllamaStatus(
                available=False,
                model=self._model,
                model_present=False,
                detail="Ollama returned a malformed model list.",
            )

        installed = {
            str(entry.get("name") or entry.get("model") or "")
            for entry in payload.get("models", [])
            if isinstance(entry, dict)
        }
        present = self._model in installed
        if present:
            detail = "Ollama is running and the configured model is installed."
        else:
            detail = (
                "Ollama is running but the configured model is not installed. "
                f"Run: ollama pull {self._model}"
            )
        return OllamaStatus(
            available=True,
            model=self._model,
            model_present=present,
            detail=detail,
        )

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        response_format: str | None = None,
    ) -> str:
        """Generate a completion for ``prompt`` using the configured model.

        ``response_format`` maps to Ollama's ``format`` field; pass ``"json"``
        to constrain decoding to valid JSON.
        """
        payload: dict[str, object] = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": GENERATION_OPTIONS,
        }
        if system:
            payload["system"] = system
        if response_format:
            payload["format"] = response_format

        client = self._get_client()
        try:
            response = await client.post("/api/generate", json=payload)
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(
                f"Ollama did not respond within {self._timeout_s:g}s."
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("Ollama request failed: %s", exc)
            raise OllamaUnavailableError(
                f"Ollama is not reachable at {self._base_url}."
            ) from exc

        if response.status_code == httpx.codes.NOT_FOUND:
            raise OllamaUnavailableError(
                f"Model '{self._model}' is not available in Ollama. "
                f"Run: ollama pull {self._model}"
            )
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise OllamaError(
                f"Ollama returned HTTP {response.status_code} for this request."
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise OllamaError("Ollama returned a malformed response body.") from exc

        text = str(data.get("response", "")).strip()
        if not text:
            raise OllamaError("Ollama returned an empty completion.")
        return text


_service: OllamaService | None = None


def get_ollama_service() -> OllamaService:
    """Return the process-wide Ollama client."""
    global _service
    if _service is None:
        settings = get_settings()
        _service = OllamaService(
            base_url=settings.ollama_url,
            model=settings.llm_model,
            timeout_s=settings.llm_timeout_s,
        )
    return _service


async def shutdown_ollama_service() -> None:
    """Release the Ollama connection pool on application shutdown."""
    global _service
    if _service is not None:
        await _service.aclose()
        _service = None
