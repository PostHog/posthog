from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.llm.gateway_client import GatewayNotConfiguredError

from products.tasks.backend.logic.model_override import ModelOverride, ModelOverrideAttribution, classify_model_override
from products.tasks.backend.logic.services.model_catalogue import ModelChoice

ATTRIBUTION = ModelOverrideAttribution(ai_product="posthog_ai", properties={})
CHOICES = (
    ModelChoice("claude", "claude-opus-5", "Claude Opus 5", ("low", "medium", "high", "max")),
    ModelChoice("claude", "claude-fable-5", "Claude Fable 5", ("low", "medium", "high")),
    ModelChoice("codex", "gpt-5.6-sol", "gpt-5.6-sol", ("low", "medium", "high", "max")),
)
BUILD_CLIENT = "products.tasks.backend.logic.model_override.build_ai_gateway_openai_client"
NO_OVERRIDE_REPLY = '{"model": null, "reasoning_effort": null}'


def _fake_client(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    client = MagicMock()
    # `with_options` returns a configured copy, so the fake hands back itself to keep
    # one set of call records no matter how the call site bounds the client.
    client.with_options.return_value = client
    client.chat.completions.create.return_value = response
    return client


def _request_sent_for(content: str) -> dict:
    fake_client = _fake_client(content)
    with patch(BUILD_CLIENT, return_value=fake_client):
        classify_model_override("use fable for this", CHOICES, ATTRIBUTION)
    return fake_client.chat.completions.create.call_args.kwargs


class TestClassifyModelOverride(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "model_and_effort",
                '{"model": "claude-fable-5", "reasoning_effort": "high"}',
                ModelOverride(model="claude-fable-5", reasoning_effort="high"),
            ),
            (
                "model_only",
                '{"model": "claude-fable-5", "reasoning_effort": null}',
                ModelOverride(model="claude-fable-5", reasoning_effort=None),
            ),
            # An effort can be asked for without naming a model; the model the run
            # already had stays, and the merge happens at the point of use.
            (
                "effort_only",
                '{"model": null, "reasoning_effort": "max"}',
                ModelOverride(model=None, reasoning_effort="max"),
            ),
            # A reply is not reliably unfenced through the gateway.
            (
                "fenced_json",
                '```json\n{"model": "claude-fable-5", "reasoning_effort": null}\n```',
                ModelOverride(model="claude-fable-5", reasoning_effort=None),
            ),
            (
                "case_insensitive_id",
                '{"model": "Claude-Fable-5"}',
                ModelOverride(model="claude-fable-5", reasoning_effort=None),
            ),
            # An effort the chosen model can't do is dropped where the run's preferences
            # are resolved, not here, so it survives the classifier untouched.
            (
                "model_with_unsupported_effort",
                '{"model": "claude-fable-5", "reasoning_effort": "turbo"}',
                ModelOverride(model="claude-fable-5", reasoning_effort="turbo"),
            ),
            # The common case: a message that merely names a model is not an instruction,
            # and nulls are how the classifier says so.
            ("both_null", NO_OVERRIDE_REPLY, None),
            ("fields_missing", "{}", None),
            # A model we can't drive is a hallucination or an unsupported ask; either
            # way the run must fall back to the resolved preferences.
            ("unknown_model", '{"model": "gemini-3-pro", "reasoning_effort": null}', None),
            ("empty_reply", "", None),
            ("prose_reply", "I think they want fable.", None),
            ("wrong_types", '{"model": 5, "reasoning_effort": []}', None),
        ]
    )
    def test_override_from_classifier_reply(self, _name: str, content: str, expected: ModelOverride | None) -> None:
        with patch(BUILD_CLIENT, return_value=_fake_client(content)):
            assert classify_model_override("use fable for this", CHOICES, ATTRIBUTION) == expected

    @parameterized.expand(
        [
            ("gateway_error", RuntimeError("boom")),
            ("gateway_unconfigured", GatewayNotConfiguredError("AI_GATEWAY_URL is not set")),
        ]
    )
    def test_llm_failure_falls_back_to_no_override(self, _name: str, error: Exception) -> None:
        with (
            patch(BUILD_CLIENT, side_effect=error),
            patch("products.tasks.backend.logic.model_override.logger") as logger,
        ):
            assert classify_model_override("use fable for this", CHOICES, ATTRIBUTION) is None

        logger.exception.assert_called_once_with("model_override_classify_failed", ai_product="posthog_ai")

    def test_reply_is_pinned_to_the_catalogue(self) -> None:
        # The schema, not the prompt, is what stops the classifier naming a model the caller
        # can't drive. If the request stops carrying the enum, `find_model_choice` silently
        # becomes the only thing standing between a hallucinated id and a dropped override.
        schema = _request_sent_for(NO_OVERRIDE_REPLY)["response_format"]["json_schema"]

        assert schema["strict"] is True
        assert schema["schema"]["properties"]["model"]["enum"] == [
            "claude-opus-5",
            "claude-fable-5",
            "gpt-5.6-sol",
            None,
        ]
        # Which efforts a model supports depends on the model the run lands on, so the
        # effort is deliberately left open here and settled where preferences resolve.
        assert "enum" not in schema["schema"]["properties"]["reasoning_effort"]

    def test_token_cap_uses_the_reasoning_model_parameter(self) -> None:
        # The route 400s on `max_tokens`, and the except turns that into a silent "no override".
        request = _request_sent_for(NO_OVERRIDE_REPLY)

        assert "max_tokens" not in request
        assert request["max_completion_tokens"] > 0
