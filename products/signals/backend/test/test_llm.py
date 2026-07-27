import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from products.signals.backend.temporal.emit_eval_signal import (
    EmitEvalSignalInputs,
    EvalSignalSummary,
    summarize_eval_for_signal,
)
from products.signals.backend.temporal.llm import call_llm
from products.signals.eval.llm_gen.client import CanonicalSignal, CanonicalSignalBatch, generate_canonical_signals

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
async def test_eval_signal_summary_opts_in_as_signals_eval():
    inputs = EmitEvalSignalInputs(
        team_id=1,
        evaluation_id="eval-1",
        evaluation_name="name",
        evaluation_prompt="prompt",
        event_uuid="event-1",
        event_type="generation",
        trace_id="trace-1",
        reasoning="reasoning",
        model="claude-sonnet-4-5",
        provider="anthropic",
    )
    summary = EvalSignalSummary(title="t", description="d", significance=0.5)
    with patch(
        "products.signals.backend.temporal.emit_eval_signal.call_llm", new=AsyncMock(return_value=summary)
    ) as summary_call:
        await summarize_eval_for_signal(inputs)

    kwargs = summary_call.call_args.kwargs
    assert kwargs["ai_product"] == "signals_eval"
    assert kwargs["stage"] == "eval_signal_summary"
