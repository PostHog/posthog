from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai
import pytest

from llm_gateway.openai_credentials import OpenAICredentialError, verify_openai_credentials


def _make_settings(**overrides: Any) -> MagicMock:
    return MagicMock(
        **{
            "openai_credential_check_enabled": True,
            "openai_api_key": "sk-test",
            "openai_api_base_url": None,
            "openai_organization": "org-test",
            **overrides,
        }
    )


def _openai_status_error(status_code: int, code: str | None = None) -> openai.APIStatusError:
    body = {"error": {"code": code}}
    response = httpx.Response(
        status_code,
        request=httpx.Request("GET", "https://api.openai.com/v1/models"),
        json=body,
    )
    error_class = openai.AuthenticationError if status_code == 401 else openai.APIStatusError
    return error_class("provider rejected the request", response=response, body=body)


def _patch_client(answer: Exception | None = None) -> tuple[Any, AsyncMock]:
    client = AsyncMock()
    if answer is not None:
        client.models.list.side_effect = answer
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    return patch("llm_gateway.openai_credentials.openai.AsyncOpenAI", return_value=context), client


@pytest.fixture(autouse=True)
def _isolate_openai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in ("OPENAI_API_KEY", "OPENAI_ORG_ID", "OPENAI_BASE_URL"):
        monkeypatch.delenv(variable, raising=False)


class TestVerifyOpenAICredentials:
    async def test_rejects_a_key_the_organization_does_not_own(self) -> None:
        client_patch, _ = _patch_client(_openai_status_error(401, "invalid_organization"))

        with client_patch, pytest.raises(OpenAICredentialError, match="invalid_organization"):
            await verify_openai_credentials(_make_settings())

    async def test_uses_the_effective_sdk_configuration(self) -> None:
        client_patch, client = _patch_client()
        settings = _make_settings(openai_api_base_url="https://eu.api.openai.com/v1")

        with client_patch as client_class:
            await verify_openai_credentials(settings)

        assert client_class.call_args.kwargs["api_key"] == "sk-test"
        assert client_class.call_args.kwargs["organization"] == "org-test"
        assert client_class.call_args.kwargs["base_url"] == "https://eu.api.openai.com/v1"
        assert client_class.call_args.kwargs["max_retries"] == 0
        client.models.list.assert_awaited_once()

    async def test_uses_ambient_sdk_configuration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-ambient")
        monkeypatch.setenv("OPENAI_ORG_ID", "org-ambient")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://proxy.example.com/v1")
        client_patch, _ = _patch_client()

        with client_patch as client_class:
            await verify_openai_credentials(
                _make_settings(openai_api_key=None, openai_organization=None, openai_api_base_url=None)
            )

        assert client_class.call_args.kwargs["api_key"] == "sk-ambient"
        assert client_class.call_args.kwargs["organization"] == "org-ambient"
        assert client_class.call_args.kwargs["base_url"] == "https://proxy.example.com/v1"

    @pytest.mark.parametrize(
        "answer",
        [
            openai.APIConnectionError(request=httpx.Request("GET", "https://api.openai.com/v1/models")),
            openai.APIError(
                "invalid response",
                httpx.Request("GET", "https://api.openai.com/v1/models"),
                body=None,
            ),
            _openai_status_error(403),
            _openai_status_error(404),
            _openai_status_error(500),
        ],
    )
    async def test_starts_when_the_check_cannot_conclude(self, answer: Exception) -> None:
        client_patch, _ = _patch_client(answer)

        with client_patch:
            await verify_openai_credentials(_make_settings())

    @pytest.mark.parametrize(
        "settings",
        [
            _make_settings(openai_api_key=None),
            _make_settings(openai_credential_check_enabled=False),
        ],
    )
    async def test_skips_the_check(self, settings: MagicMock) -> None:
        client_patch, _ = _patch_client(_openai_status_error(401))

        with client_patch as client_class:
            await verify_openai_credentials(settings)

        client_class.assert_not_called()
