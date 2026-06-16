import json

import pytest
from unittest.mock import AsyncMock, patch

import httpx
import anthropic

from products.signals.backend.temporal import llm
from products.signals.backend.temporal.llm import EmptyLLMResponseError, call_llm

LLM_MODULE_PATH = "products.signals.backend.temporal.llm"


def _text_response(text: str):
    block = type("Block", (), {"type": "text", "text": text})()
    return type("Response", (), {"content": [block]})()


def _api_status_error(status_code: int) -> anthropic.APIStatusError:
    request = httpx.Request("POST", "https://gateway.invalid/v1/messages")
    response = httpx.Response(status_code, request=request)
    return anthropic.APIStatusError("boom", response=response, body=None)


def _validate(text: str) -> dict:
    return json.loads(text)


@pytest.fixture(autouse=True)
def _no_sleep():
    # Don't actually wait through backoff delays in tests.
    with patch.object(llm.asyncio, "sleep", new=AsyncMock()):
        yield


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        anthropic.InternalServerError(
            "boom", response=httpx.Response(500, request=httpx.Request("POST", "https://x")), body=None
        ),
        anthropic.RateLimitError(
            "boom", response=httpx.Response(429, request=httpx.Request("POST", "https://x")), body=None
        ),
        anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")),
        _api_status_error(503),
    ],
)
async def test_transient_api_error_is_retried_then_succeeds(error):
    client = AsyncMock()
    # Non-thinking call prefills `{`, so validate receives `{...}`.
    client.messages.create = AsyncMock(side_effect=[error, _text_response('"ok": 1}')])

    with patch(f"{LLM_MODULE_PATH}.get_async_anthropic_gateway_client", return_value=client):
        result = await call_llm(
            team_id=1,
            system_prompt="sys",
            user_prompt="hi",
            validate=_validate,
        )

    assert result == {"ok": 1}
    assert client.messages.create.await_count == 2


@pytest.mark.asyncio
async def test_transient_api_error_exhausts_retries_then_raises():
    client = AsyncMock()
    error = _api_status_error(500)
    client.messages.create = AsyncMock(side_effect=error)

    with patch(f"{LLM_MODULE_PATH}.get_async_anthropic_gateway_client", return_value=client):
        with pytest.raises(anthropic.APIStatusError):
            await call_llm(team_id=1, system_prompt="sys", user_prompt="hi", validate=_validate)

    assert client.messages.create.await_count == llm.MAX_API_RETRIES


@pytest.mark.asyncio
async def test_non_retryable_api_error_raises_immediately():
    client = AsyncMock()
    error = _api_status_error(400)
    client.messages.create = AsyncMock(side_effect=error)

    with patch(f"{LLM_MODULE_PATH}.get_async_anthropic_gateway_client", return_value=client):
        with pytest.raises(anthropic.APIStatusError):
            await call_llm(team_id=1, system_prompt="sys", user_prompt="hi", validate=_validate)

    assert client.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_empty_response_is_not_retried_as_api_error():
    client = AsyncMock()
    empty = type("Response", (), {"content": []})()
    client.messages.create = AsyncMock(return_value=empty)

    with patch(f"{LLM_MODULE_PATH}.get_async_anthropic_gateway_client", return_value=client):
        with pytest.raises(EmptyLLMResponseError):
            await call_llm(team_id=1, system_prompt="sys", user_prompt="hi", validate=_validate)

    assert client.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_validation_failure_is_retried_by_outer_loop():
    client = AsyncMock()
    client.messages.create = AsyncMock(side_effect=[_text_response("not json}"), _text_response('"ok": 1}')])

    with patch(f"{LLM_MODULE_PATH}.get_async_anthropic_gateway_client", return_value=client):
        result = await call_llm(team_id=1, system_prompt="sys", user_prompt="hi", validate=_validate)

    assert result == {"ok": 1}
    assert client.messages.create.await_count == 2
