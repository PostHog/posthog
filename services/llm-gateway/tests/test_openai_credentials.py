from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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


def _patch_client(answer: httpx.Response | Exception) -> tuple[Any, AsyncMock]:
    client = AsyncMock()
    if isinstance(answer, Exception):
        client.get.side_effect = answer
    else:
        client.get.return_value = answer
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    return patch("httpx.AsyncClient", return_value=context), client


class TestVerifyOpenAICredentials:
    async def test_rejects_a_key_the_organization_does_not_own(self) -> None:
        client_patch, _ = _patch_client(httpx.Response(401, json={"error": {"code": "invalid_organization"}}))

        with client_patch, pytest.raises(OpenAICredentialError, match="invalid_organization"):
            await verify_openai_credentials(_make_settings())

    async def test_sends_the_organization_openai_judges_the_key_against(self) -> None:
        client_patch, client = _patch_client(httpx.Response(200, json={"data": []}))

        with client_patch:
            await verify_openai_credentials(_make_settings())

        assert client.get.call_args[1]["headers"]["OpenAI-Organization"] == "org-test"

    @pytest.mark.parametrize(
        "answer",
        [httpx.ConnectError("unreachable"), httpx.Response(403), httpx.Response(404), httpx.Response(500)],
    )
    async def test_starts_when_the_check_cannot_conclude(self, answer: httpx.Response | Exception) -> None:
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
        client_patch, client = _patch_client(httpx.Response(401))

        with client_patch:
            await verify_openai_credentials(settings)

        client.get.assert_not_called()
