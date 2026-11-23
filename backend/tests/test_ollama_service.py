from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.llm_provider import LLMTimeoutError, LLMUnavailableError
from app.services.ollama_service import OllamaProvider


class StubResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class StubClient:
    def __init__(self, *, responses=None, post_response=None):
        self.responses = responses or {}
        self.post_response = post_response or StubResponse(
            200, {"response": "local answer"}
        )
        self.requests: list[dict] = []

    async def get(self, path, *, timeout=None):
        self.requests.append({"method": "GET", "path": path})
        return self.responses[path]

    async def post(self, path, *, json):
        self.requests.append({"method": "POST", "path": path, "json": json})
        if isinstance(self.post_response, Exception):
            raise self.post_response
        return self.post_response

    async def aclose(self):
        return None


def _provider() -> OllamaProvider:
    return OllamaProvider(
        "http://ollama.test:11434",
        "qwen3.5:2b",
        45,
        num_ctx=8192,
        num_predict=512,
    )


def _install_client(monkeypatch, client: StubClient) -> dict:
    captured = {}

    def create_client(**kwargs):
        captured.update(kwargs)
        return client

    monkeypatch.setattr("app.services.ollama_service.httpx.AsyncClient", create_client)
    return captured


def test_ollama_generation_preserves_prompt_and_generation_parameters(monkeypatch):
    client = StubClient()
    _install_client(monkeypatch, client)

    result = asyncio.run(
        _provider().generate(
            "Question", system="Rules", response_format="json"
        )
    )

    assert result == "local answer"
    request = client.requests[0]
    assert request["path"] == "/api/generate"
    assert request["json"] == {
        "model": "qwen3.5:2b",
        "prompt": "Question",
        "system": "Rules",
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "temperature": 0.2,
            "top_p": 0.9,
            "num_ctx": 8192,
            "num_predict": 512,
        },
    }


def test_ollama_availability_reports_configured_model(monkeypatch):
    client = StubClient(
        responses={
            "/api/tags": StubResponse(
                200, {"models": [{"name": "qwen3.5:2b"}]}
            )
        }
    )
    _install_client(monkeypatch, client)

    status = asyncio.run(_provider().check_availability())

    assert status.available is True
    assert status.model_present is True


@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        (httpx.ConnectError("unavailable"), LLMUnavailableError),
        (httpx.ReadTimeout("timeout"), LLMTimeoutError),
    ],
)
def test_ollama_failures_are_reported(monkeypatch, failure, error_type):
    client = StubClient(post_response=failure)
    _install_client(monkeypatch, client)

    with pytest.raises(error_type):
        asyncio.run(_provider().generate("Question"))
