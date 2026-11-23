from __future__ import annotations

import asyncio

import httpx
import pytest

from app.config import Settings
from app.services.llm_provider import (
    LLMAuthenticationError,
    LLMCreditsError,
    LLMError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.services.openrouter_service import OpenRouterProvider


class StubResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class StubClient:
    def __init__(self, *, responses: dict[str, StubResponse], post_response=None):
        self.responses = responses
        self.post_response = post_response or StubResponse(
            200, {"choices": [{"message": {"content": "generated"}}]}
        )
        self.requests: list[dict] = []

    async def get(self, path: str, *, timeout=None):
        self.requests.append({"method": "GET", "path": path})
        return self.responses[path]

    async def post(self, path: str, *, json):
        self.requests.append({"method": "POST", "path": path, "json": json})
        if isinstance(self.post_response, Exception):
            raise self.post_response
        return self.post_response

    async def aclose(self):
        return None


def _provider(api_key="test-key") -> OpenRouterProvider:
    return OpenRouterProvider(
        "https://openrouter.test/api/v1",
        "anthropic/claude-sonnet-5",
        api_key,
        45,
        max_tokens=1024,
    )


def test_openrouter_url_requires_https_without_embedded_credentials():
    assert Settings(openrouter_base_url="https://router.example/v1").openrouter_base_url == (
        "https://router.example/v1"
    )
    with pytest.raises(ValueError, match="OPENROUTER_BASE_URL"):
        Settings(openrouter_base_url="http://router.example/v1")
    with pytest.raises(ValueError, match="OPENROUTER_BASE_URL"):
        Settings(openrouter_base_url="https://user:password@router.example/v1")


def _install_client(monkeypatch, client: StubClient) -> dict:
    captured = {}

    def create_client(**kwargs):
        captured.update(kwargs)
        return client

    monkeypatch.setattr(
        "app.services.openrouter_service.httpx.AsyncClient", create_client
    )
    return captured


def test_generate_uses_openrouter_chat_completions_and_json_mode(monkeypatch):
    client = StubClient(responses={})
    captured = _install_client(monkeypatch, client)

    result = asyncio.run(
        _provider().generate(
            "Question", system="System rules", response_format="json"
        )
    )

    assert result == "generated"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    request = client.requests[0]
    assert request["path"] == "/chat/completions"
    assert request["json"] == {
        "model": "anthropic/claude-sonnet-5",
        "messages": [
            {"role": "system", "content": "System rules"},
            {"role": "user", "content": "Question"},
        ],
        "stream": False,
        "max_tokens": 1024,
        "temperature": 0.2,
        "top_p": 0.9,
        "response_format": {"type": "json_object"},
    }


def test_health_checks_credentials_and_configured_model(monkeypatch):
    client = StubClient(
        responses={
            "/auth/key": StubResponse(200, {"data": {"label": "test"}}),
            "/models": StubResponse(
                200,
                {"data": [{"id": "anthropic/claude-sonnet-5"}]},
            ),
        }
    )
    _install_client(monkeypatch, client)

    status = asyncio.run(_provider().check_availability())

    assert status.available is True
    assert status.model_present is True
    assert [request["path"] for request in client.requests] == [
        "/auth/key",
        "/models",
    ]


def test_health_reports_missing_api_key_without_network_request(monkeypatch):
    def unexpected_client(**kwargs):
        raise AssertionError("must not create a client without an API key")

    monkeypatch.setattr(
        "app.services.openrouter_service.httpx.AsyncClient", unexpected_client
    )

    status = asyncio.run(_provider(api_key="").check_availability())

    assert status.available is False
    assert status.model_present is False
    assert "OPENROUTER_API_KEY" in status.detail


def test_generation_rejects_missing_api_key_without_network_request(monkeypatch):
    def unexpected_client(**kwargs):
        raise AssertionError("must not create a client without an API key")

    monkeypatch.setattr(
        "app.services.openrouter_service.httpx.AsyncClient", unexpected_client
    )

    with pytest.raises(LLMUnavailableError, match="OPENROUTER_API_KEY"):
        asyncio.run(_provider(api_key="").generate("Question"))


def test_unknown_model_is_reported_as_unavailable(monkeypatch):
    client = StubClient(
        responses={
            "/auth/key": StubResponse(200, {"data": {}}),
            "/models": StubResponse(200, {"data": [{"id": "some/other-model"}]}),
        }
    )
    _install_client(monkeypatch, client)

    status = asyncio.run(_provider().check_availability())

    assert status.available is False
    assert status.model_present is False


def test_invalid_model_catalogue_is_reported_as_unavailable(monkeypatch):
    client = StubClient(
        responses={
            "/auth/key": StubResponse(200, {"data": {}}),
            "/models": StubResponse(200, {"data": None}),
        }
    )
    _install_client(monkeypatch, client)

    status = asyncio.run(_provider().check_availability())

    assert status.available is False
    assert "invalid model catalogue" in status.detail


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, LLMAuthenticationError),
        (404, LLMError),
        (402, LLMCreditsError),
        (429, LLMUnavailableError),
        (500, LLMUnavailableError),
        (502, LLMUnavailableError),
        (503, LLMUnavailableError),
        (504, LLMUnavailableError),
    ],
)
def test_generation_surfaces_openrouter_failures(monkeypatch, status_code, error_type):
    client = StubClient(
        responses={},
        post_response=StubResponse(status_code, {"error": {"message": "ignored"}}),
    )
    _install_client(monkeypatch, client)

    with pytest.raises(error_type):
        asyncio.run(_provider().generate("Question"))


def test_generation_timeout_is_reported(monkeypatch):
    client = StubClient(responses={}, post_response=httpx.ReadTimeout("timeout"))
    _install_client(monkeypatch, client)

    with pytest.raises(LLMTimeoutError):
        asyncio.run(_provider().generate("Question"))


def test_malformed_success_response_is_recoverable(monkeypatch):
    client = StubClient(responses={})
    client.post_response = StubResponse(200, {"choices": []})
    _install_client(monkeypatch, client)

    with pytest.raises(LLMResponseError):
        asyncio.run(_provider().generate("Question"))
