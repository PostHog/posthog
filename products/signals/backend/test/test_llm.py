import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from anthropic.types import Message, TextBlock, Usage

from products.signals.backend.temporal.llm import MalformedLLMResponseError, call_llm
from products.signals.eval.llm_gen.client import CanonicalSignal, CanonicalSignalBatch, generate_canonical_signals

MODULE_PATH = "products.signals.backend.temporal.llm"


def _text_response(text: str) -> Message:
    return Message(
        id="msg_test",
        content=[TextBlock(text=text, type="text")],
        model="claude-sonnet-4-5",
        role="assistant",
        type="message",
        usage=Usage(input_tokens=1, output_tokens=1),
    )


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


@pytest.mark.asyncio
@override_settings(AI_GATEWAY_URL="https://ai-gateway.example/v1", AI_GATEWAY_API_KEY="phs_test")
async def test_non_message_response_retries_then_recovers():
    # A gateway blip that hands back a non-Message body must not discard the whole call: the loop
    # takes another attempt and the next valid reply succeeds.
    client = _mock_anthropic_client()
    client.messages.create = AsyncMock(side_effect=["not json", _text_response("ok")])

    with (
        patch(f"{MODULE_PATH}.build_async_anthropic_client", return_value=client),
        patch(f"{MODULE_PATH}.metrics.increment_llm_call") as increment_llm_call,
    ):
        result = await call_llm(
            team_id=1,
            system_prompt="s",
            user_prompt="u",
            validate=lambda text: text,
            stage="match",
            ai_product="signals_grouping",
        )

    assert result == "{ok"
    assert client.messages.create.call_count == 2
    # The malformed reply is counted under its own status even though the retry recovers, so the
    # gateway degradation rate stays observable instead of hiding behind the final "ok".
    assert ("match", "malformed") in {args for args, _ in increment_llm_call.call_args_list}
    assert ("match", "ok") in {args for args, _ in increment_llm_call.call_args_list}


@pytest.mark.asyncio
@override_settings(AI_GATEWAY_URL="https://ai-gateway.example/v1", AI_GATEWAY_API_KEY="phs_test")
async def test_non_message_response_raises_descriptive_error_after_retries():
    client = _mock_anthropic_client()
    client.messages.create.return_value = "not json"

    with (
        patch(f"{MODULE_PATH}.build_async_anthropic_client", return_value=client),
        pytest.raises(MalformedLLMResponseError, match="Expected Anthropic Message response, got str: 'not json'"),
    ):
        await call_llm(
            team_id=1,
            system_prompt="s",
            user_prompt="u",
            validate=lambda text: text,
            stage="match",
            ai_product="signals_grouping",
            retries=2,
        )

    assert client.messages.create.call_count == 2


# `ai_product` is the opt-in switch, not just a label: dropping it from a call site silently
# reverts that site to the Python gateway and unattributes its spend, with no failing call to
# notice. Each site that opts in pins its own tag and stage.


@pytest.mark.asyncio
async def test_eval_fixture_generation_opts_in_as_signals_eval():
    batch = CanonicalSignalBatch(signals=[CanonicalSignal(title="a" * 10, body="b" * 20)])
    with patch("products.signals.eval.llm_gen.client.call_llm", new=AsyncMock(return_value=batch)) as generation_call:
        await generate_canonical_signals(team_id=1, system_prompt="s", user_prompt="u")

    kwargs = generation_call.call_args.kwargs
    assert kwargs["ai_product"] == "signals_eval"
    assert kwargs["stage"] == "eval_signal_generation"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model,thinking,expect_prefill,expect_temperature,expect_thinking,expect_effort",
    [
        ("claude-sonnet-4-5", False, True, True, None, None),
        ("claude-sonnet-4-5", True, False, True, "enabled", None),
        ("claude-sonnet-5", False, False, False, None, "medium"),
        ("claude-sonnet-5", True, False, False, "adaptive", "medium"),
        ("claude-sonnet-4-6", False, False, True, None, "medium"),
    ],
)
async def test_request_shape_follows_model_capabilities(
    model, thinking, expect_prefill, expect_temperature, expect_thinking, expect_effort
):
    client = _mock_anthropic_client()
    with (
        patch(f"{MODULE_PATH}.MATCHING_MODEL", model),
        patch(f"{MODULE_PATH}.get_async_anthropic_gateway_client", return_value=client),
    ):
        await call_llm(
            team_id=1,
            system_prompt="s",
            user_prompt="u",
            validate=lambda text: text,
            thinking=thinking,
            stage="match",
        )

    kwargs = client.messages.create.call_args.kwargs
    prefilled = kwargs["messages"][-1]["role"] == "assistant"
    assert prefilled is expect_prefill
    assert ("temperature" in kwargs) is expect_temperature
    assert (kwargs.get("thinking") or {}).get("type") == expect_thinking
    assert kwargs.get("output_config") == ({"effort": expect_effort} if expect_effort else None)
