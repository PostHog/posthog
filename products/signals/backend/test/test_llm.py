import os
import runpy

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from anthropic.types import Message, TextBlock, Usage

from products.signals.backend.temporal import llm
from products.signals.backend.temporal.llm import (
    EmptyLLMResponseError,
    LLMRefusalError,
    LLMResponseValidationError,
    call_llm,
    parse_json_object,
)
from products.signals.backend.temporal.safety_filter import SafetyFilterJudgeResponse
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
    with patch(f"{MODULE_PATH}.build_async_anthropic_client", return_value=client) as build_client:
        await call_llm(
            team_id=1,
            system_prompt="s",
            user_prompt="u",
            validate=lambda text: text,
            stage="match",
            ai_product="signals_grouping",
            trace_id="decision-1",
            properties={"signals_decision_id": "decision-1"},
        )

    assert build_client.call_args.kwargs["trace_id"] == "decision-1"
    assert build_client.call_args.kwargs["properties"] == {"signals_decision_id": "decision-1"}
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
@pytest.mark.parametrize(
    "cache_system_prompt,expected_system",
    [
        (False, "s"),
        (True, [{"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}]),
    ],
)
async def test_cache_system_prompt_marks_the_system_block(
    cache_system_prompt: bool, expected_system: str | list[dict[str, object]]
) -> None:
    client = _mock_anthropic_client()
    with patch(f"{MODULE_PATH}.build_async_anthropic_client", return_value=client):
        await call_llm(
            team_id=1,
            system_prompt="s",
            user_prompt="u",
            validate=lambda text: text,
            stage="safety_filter",
            ai_product="signals_safety",
            cache_system_prompt=cache_system_prompt,
        )

    assert client.messages.create.call_args.kwargs["system"] == expected_system


@pytest.mark.asyncio
@override_settings(AI_GATEWAY_URL="https://ai-gateway.example/v1", AI_GATEWAY_API_KEY="phs_test")
async def test_non_message_response_raises_descriptive_error():
    client = _mock_anthropic_client()
    client.messages.create.return_value = "not json"

    with (
        patch(f"{MODULE_PATH}.build_async_anthropic_client", return_value=client),
        pytest.raises(TypeError, match="Expected Anthropic Message response, got str"),
    ):
        await call_llm(
            team_id=1,
            system_prompt="s",
            user_prompt="u",
            validate=lambda text: text,
            stage="match",
            ai_product="signals_grouping",
        )


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
        ("claude-sonnet-5-5", False, False, False, None, "medium"),
        ("claude-sonnet-5-5", True, False, False, "adaptive", "medium"),
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


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"match": true}', {"match": True}),
        (' \n{"match": false, "reason": "a {b}"}\t', {"match": False, "reason": "a {b}"}),
    ],
)
def test_parse_json_object_accepts_one_complete_object(text: str, expected: dict[str, object]) -> None:
    assert parse_json_object(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "no json here",
        '{"match": true,, "x": 1}',
        '{"result": {"safe": true}, broken}',
        '{"safe": true} trailing prose',
        'Here is the result: {"safe": true}',
        '```json\n{"safe": true}\n```',
        '{"safe": true} {"safe": false}',
        '{"safe": true} null',
        '[{"safe": true}]',
        "true",
        "null",
        '{"safe": true, "safe": false}',
        '{"result": {"safe": true, "safe": false}}',
        '{"score": NaN}',
        '{"score": Infinity}',
        '{"score": -Infinity}',
        '{"score": 1e999}',
    ],
)
def test_parse_json_object_rejects_invalid_json(text: str) -> None:
    with pytest.raises(LLMResponseValidationError):
        parse_json_object(text)


@pytest.mark.asyncio
@pytest.mark.parametrize("json_response", [False, True])
async def test_json_response_mode_controls_fence_handling(json_response: bool) -> None:
    client = _mock_anthropic_client()
    client.messages.create.side_effect = [
        _text_response('```json\n{"safe": true}\n```'),
        _text_response('{"safe": true}'),
    ]
    with patch(f"{MODULE_PATH}.build_async_anthropic_client", return_value=client):
        result = await call_llm(
            team_id=1,
            system_prompt="s",
            user_prompt="u",
            validate=parse_json_object,
            ai_product="signals_grouping",
            model="claude-sonnet-5-5",
            json_response=json_response,
        )

    assert result == {"safe": True}
    assert client.messages.create.await_count == (2 if json_response else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["claude-sonnet-4-5", "claude-sonnet-5-5"])
async def test_json_response_combines_text_blocks_and_reconstructs_prefill(model: str) -> None:
    client = _mock_anthropic_client()
    client.messages.create.return_value = Message.model_validate(
        {
            **_text_response("").model_dump(),
            "content": [
                {"type": "thinking", "thinking": "Internal reasoning", "signature": "test"},
                {"type": "text", "text": '"safe":' if model == "claude-sonnet-4-5" else '{"safe":'},
                {"type": "text", "text": "true}"},
            ],
        }
    )
    with patch(f"{MODULE_PATH}.build_async_anthropic_client", return_value=client):
        result = await call_llm(
            team_id=1,
            system_prompt="s",
            user_prompt="u",
            validate=parse_json_object,
            ai_product="signals_grouping",
            model=model,
            json_response=True,
        )

    assert result == {"safe": True}
    kwargs = client.messages.create.call_args.kwargs
    assert "exactly one complete JSON object" in kwargs["messages"][0]["content"]
    assert (kwargs["messages"][-1]["role"] == "assistant") == (model == "claude-sonnet-4-5")
    assert "format" not in kwargs.get("output_config", {})


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_reason", ["max_tokens", "model_context_window_exceeded"])
async def test_truncated_json_response_retries_even_when_text_is_valid(stop_reason: str) -> None:
    client = _mock_anthropic_client()
    client.messages.create.side_effect = [
        _text_response('{"safe": false}').model_copy(update={"stop_reason": stop_reason}),
        _text_response('{"safe": true}'),
    ]
    with patch(f"{MODULE_PATH}.build_async_anthropic_client", return_value=client):
        result = await call_llm(
            team_id=1,
            system_prompt="s",
            user_prompt="u",
            validate=parse_json_object,
            ai_product="signals_grouping",
            model="claude-sonnet-5-5",
            json_response=True,
        )

    assert result == {"safe": True}
    assert client.messages.create.await_count == 2
    assert "truncated" in client.messages.create.call_args.kwargs["messages"][2]["content"]


@pytest.mark.asyncio
@override_settings(DEBUG=False)
async def test_validation_feedback_omits_response_values_and_extra_field_names() -> None:
    client = _mock_anthropic_client()
    client.messages.create.side_effect = [
        _text_response('{"safe": "fake-secret-value", "fake-secret-key": true}'),
        _text_response('{"safe": true}'),
    ]
    with (
        patch(f"{MODULE_PATH}.build_async_anthropic_client", return_value=client),
        patch(f"{MODULE_PATH}.logger") as logger,
    ):
        result = await call_llm(
            team_id=1,
            system_prompt="s",
            user_prompt="u",
            validate=lambda text: SafetyFilterJudgeResponse.model_validate(parse_json_object(text)),
            ai_product="signals_safety",
            model="claude-sonnet-5-5",
            json_response=True,
        )

    assert result.safe is True
    feedback = client.messages.create.call_args.kwargs["messages"][2]["content"]
    assert "bool_type at safe" in feedback
    assert "extra_forbidden" in feedback
    assert "fake-secret" not in feedback
    assert "fake-secret" not in str(logger.warning.call_args_list)


@pytest.mark.asyncio
async def test_json_validation_exhaustion_propagates_without_a_verdict() -> None:
    client = _mock_anthropic_client()
    client.messages.create.return_value = _text_response('{"safe": true} {"safe": false}')
    with (
        patch(f"{MODULE_PATH}.build_async_anthropic_client", return_value=client),
        pytest.raises(LLMResponseValidationError),
    ):
        await call_llm(
            team_id=1,
            system_prompt="s",
            user_prompt="u",
            validate=parse_json_object,
            ai_product="signals_safety",
            model="claude-sonnet-5-5",
            json_response=True,
        )
    assert client.messages.create.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["refusal", "empty", "transport"])
async def test_json_response_terminal_failures_do_not_retry(failure: str) -> None:
    client = _mock_anthropic_client()
    expected_error: type[Exception]
    if failure == "transport":
        client.messages.create.side_effect = RuntimeError("transport failed")
        expected_error = RuntimeError
    elif failure == "empty":
        client.messages.create.return_value = _text_response("")
        expected_error = EmptyLLMResponseError
    else:
        client.messages.create.return_value = _text_response('{"safe": true}').model_copy(
            update={"stop_reason": "refusal"}
        )
        expected_error = LLMRefusalError
    with (
        patch(f"{MODULE_PATH}.build_async_anthropic_client", return_value=client),
        pytest.raises(expected_error),
    ):
        await call_llm(
            team_id=1,
            system_prompt="s",
            user_prompt="u",
            validate=parse_json_object,
            ai_product="signals_safety",
            model="claude-sonnet-5-5",
            json_response=True,
        )
    assert client.messages.create.await_count == 1


@pytest.mark.asyncio
async def test_explicit_model_overrides_the_matching_model() -> None:
    client = _mock_anthropic_client()
    with (
        patch(f"{MODULE_PATH}.MATCHING_MODEL", "claude-sonnet-4-5"),
        patch(f"{MODULE_PATH}.get_async_anthropic_gateway_client", return_value=client),
    ):
        await call_llm(
            team_id=1,
            system_prompt="s",
            user_prompt="u",
            validate=lambda text: text,
            stage="safety_filter",
            model="claude-sonnet-5",
        )

    kwargs = client.messages.create.call_args.kwargs

    # The capabilities follow the override, not MATCHING_MODEL, so dropping it flips all three.
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["messages"][-1]["role"] == "user"
    assert "temperature" not in kwargs


def _model_constants_in_environment(env: dict[str, str]) -> tuple[str, str]:
    with patch.dict(os.environ, env):
        for key in ("SIGNAL_MATCHING_LLM_MODEL", "SIGNAL_SAFETY_LLM_MODEL"):
            if key not in env:
                os.environ.pop(key, None)
        constants = runpy.run_path(llm.__file__)
        return constants["MATCHING_MODEL"], constants["SAFETY_MODEL"]


@pytest.mark.parametrize(
    "env,expected_matching,expected_safety",
    [
        ({}, "claude-sonnet-5-5", "claude-sonnet-5-5"),
        ({"SIGNAL_MATCHING_LLM_MODEL": "claude-opus-5"}, "claude-opus-5", "claude-sonnet-5-5"),
        (
            {"SIGNAL_MATCHING_LLM_MODEL": "claude-opus-5", "SIGNAL_SAFETY_LLM_MODEL": "claude-haiku-4-5"},
            "claude-opus-5",
            "claude-haiku-4-5",
        ),
    ],
)
def test_safety_model_does_not_follow_the_matching_model(
    env: dict[str, str], expected_matching: str, expected_safety: str
) -> None:
    matching, safety = _model_constants_in_environment(env)

    assert matching == expected_matching
    assert safety == expected_safety
