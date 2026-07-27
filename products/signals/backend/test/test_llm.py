import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from products.signals.backend.temporal.llm import call_llm

MODULE_PATH = "products.signals.backend.temporal.llm"


def _text_response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _mock_anthropic_client() -> MagicMock:
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=_text_response("ok"))
    return client


@pytest.mark.asyncio
@override_settings(AI_GATEWAY_URL="https://ai-gateway.example/v1", AI_GATEWAY_API_KEY="phs_test")
async def test_gateway_mode_omits_legacy_stage_header():
    client = _mock_anthropic_client()
    with patch(f"{MODULE_PATH}.build_async_anthropic_client", return_value=client):
        await call_llm(
            team_id=1,
            system_prompt="s",
            user_prompt="u",
            validate=lambda text: text,
            stage="match",
            ai_product="signals_grouping",
        )

    # In gateway mode the labels ride on the builder's X-PostHog-Properties blob; the per-key
    # ai_stage header (which the Go gateway drops) must not be sent.
    assert "extra_headers" not in client.messages.create.call_args.kwargs


@pytest.mark.asyncio
@override_settings(AI_GATEWAY_URL="", AI_GATEWAY_API_KEY="")
async def test_fallback_mode_sends_legacy_stage_header():
    client = _mock_anthropic_client()
    with patch(f"{MODULE_PATH}.build_async_anthropic_client", return_value=client):
        await call_llm(
            team_id=1,
            system_prompt="s",
            user_prompt="u",
            validate=lambda text: text,
            stage="match",
            ai_product="signals_grouping",
        )

    # On the Python-gateway fallback the stage still rides as a per-key header the route reads.
    assert client.messages.create.call_args.kwargs["extra_headers"] == {"x-posthog-property-ai_stage": "match"}


@pytest.mark.asyncio
@override_settings(AI_GATEWAY_URL="https://ai-gateway.example/v1", AI_GATEWAY_API_KEY="phs_test")
async def test_without_ai_product_stays_on_python_gateway_even_with_env_set():
    client = _mock_anthropic_client()
    with (
        patch(f"{MODULE_PATH}.get_async_anthropic_gateway_client", return_value=client) as legacy,
        patch(f"{MODULE_PATH}.build_async_anthropic_client") as gateway,
    ):
        await call_llm(team_id=1, system_prompt="s", user_prompt="u", validate=lambda text: text, stage="match")

    # A call site that hasn't opted in (no ai_product) never touches the Go-gateway builder, even
    # with the env configured, and keeps the legacy per-key stage header.
    legacy.assert_called_once()
    gateway.assert_not_called()
    assert client.messages.create.call_args.kwargs["extra_headers"] == {"x-posthog-property-ai_stage": "match"}
