"""
Integration tests for LiteLLM callbacks.

Verifies that callbacks are properly invoked during actual LLM requests.
Skipped unless ANTHROPIC_API_KEY is set.
"""

import os
from unittest.mock import patch

import pytest
from anthropic import Anthropic
from openai import OpenAI

from llm_gateway.metrics.prometheus import CALLBACK_SUCCESS, TOKENS_INPUT, TOKENS_OUTPUT

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")


class TestCallbacksFireOnAnthropicRequest:
    pytestmark = pytest.mark.skipif(not ANTHROPIC_API_KEY, reason="ANTHROPIC_API_KEY not set")

    def test_callbacks_fire_on_non_streaming_request(self, anthropic_client: Anthropic) -> None:
        initial_rate_limit = CALLBACK_SUCCESS.labels(callback="rate_limit")._value.get()
        initial_prometheus = CALLBACK_SUCCESS.labels(callback="prometheus")._value.get()

        anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            messages=[{"role": "user", "content": "Say 'test'"}],
            max_tokens=5,
        )

        assert CALLBACK_SUCCESS.labels(callback="rate_limit")._value.get() > initial_rate_limit
        assert CALLBACK_SUCCESS.labels(callback="prometheus")._value.get() > initial_prometheus

    def test_callbacks_fire_on_streaming_request(self, anthropic_client: Anthropic) -> None:
        initial_rate_limit = CALLBACK_SUCCESS.labels(callback="rate_limit")._value.get()
        initial_prometheus = CALLBACK_SUCCESS.labels(callback="prometheus")._value.get()

        with anthropic_client.messages.stream(
            model="claude-3-haiku-20240307",
            messages=[{"role": "user", "content": "Say 'hi'"}],
            max_tokens=5,
        ) as stream:
            stream.get_final_text()

        assert CALLBACK_SUCCESS.labels(callback="rate_limit")._value.get() > initial_rate_limit
        assert CALLBACK_SUCCESS.labels(callback="prometheus")._value.get() > initial_prometheus

    def test_prometheus_callback_records_tokens(self, anthropic_client: Anthropic) -> None:
        initial_input = TOKENS_INPUT.labels(
            provider="anthropic", model="claude-3-haiku-20240307", product="llm_gateway"
        )._value.get()
        initial_output = TOKENS_OUTPUT.labels(
            provider="anthropic", model="claude-3-haiku-20240307", product="llm_gateway"
        )._value.get()

        anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            messages=[{"role": "user", "content": "Say 'a'"}],
            max_tokens=5,
        )

        assert (
            TOKENS_INPUT.labels(
                provider="anthropic", model="claude-3-haiku-20240307", product="llm_gateway"
            )._value.get()
            > initial_input
        )
        assert (
            TOKENS_OUTPUT.labels(
                provider="anthropic", model="claude-3-haiku-20240307", product="llm_gateway"
            )._value.get()
            > initial_output
        )


class TestCallbacksFireOnOpenAIRequest:
    pytestmark = pytest.mark.skipif(not OPENAI_API_KEY, reason="OPENAI_API_KEY not set")

    def test_callbacks_fire_on_non_streaming_request(self, openai_client: OpenAI) -> None:
        initial_rate_limit = CALLBACK_SUCCESS.labels(callback="rate_limit")._value.get()
        initial_prometheus = CALLBACK_SUCCESS.labels(callback="prometheus")._value.get()

        openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say 'test'"}],
            max_tokens=5,
        )

        assert CALLBACK_SUCCESS.labels(callback="rate_limit")._value.get() > initial_rate_limit
        assert CALLBACK_SUCCESS.labels(callback="prometheus")._value.get() > initial_prometheus

    def test_callbacks_fire_on_streaming_request(self, openai_client: OpenAI) -> None:
        initial_rate_limit = CALLBACK_SUCCESS.labels(callback="rate_limit")._value.get()
        initial_prometheus = CALLBACK_SUCCESS.labels(callback="prometheus")._value.get()

        stream = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Say 'hi'"}],
            max_tokens=5,
            stream=True,
        )
        for _ in stream:
            pass

        assert CALLBACK_SUCCESS.labels(callback="rate_limit")._value.get() > initial_rate_limit
        assert CALLBACK_SUCCESS.labels(callback="prometheus")._value.get() > initial_prometheus


class TestCallbacksReceiveCorrectData:
    pytestmark = pytest.mark.skipif(not ANTHROPIC_API_KEY, reason="ANTHROPIC_API_KEY not set")

    def test_callback_receives_token_counts(self, anthropic_client: Anthropic) -> None:
        received_data = {}

        async def capture_on_success(self, kwargs, response_obj, start_time, end_time, end_user_id):
            standard_logging_object = kwargs.get("standard_logging_object", {})
            received_data["prompt_tokens"] = standard_logging_object.get("prompt_tokens")
            received_data["completion_tokens"] = standard_logging_object.get("completion_tokens")
            received_data["model"] = standard_logging_object.get("model")
            received_data["provider"] = standard_logging_object.get("custom_llm_provider")

        from llm_gateway.callbacks.prometheus import PrometheusCallback

        with patch.object(PrometheusCallback, "_on_success", capture_on_success):
            anthropic_client.messages.create(
                model="claude-3-haiku-20240307",
                messages=[{"role": "user", "content": "Say 'x'"}],
                max_tokens=5,
            )

        prompt_tokens = received_data.get("prompt_tokens")
        completion_tokens = received_data.get("completion_tokens")
        assert prompt_tokens is not None
        assert prompt_tokens > 0
        assert completion_tokens is not None
        assert completion_tokens > 0
        assert "claude" in received_data.get("model", "").lower()
        assert received_data.get("provider") == "anthropic"

    def test_callback_receives_streaming_token_counts(self, anthropic_client: Anthropic) -> None:
        received_data = {}

        async def capture_on_success(self, kwargs, response_obj, start_time, end_time, end_user_id):
            standard_logging_object = kwargs.get("standard_logging_object", {})
            received_data["prompt_tokens"] = standard_logging_object.get("prompt_tokens")
            received_data["completion_tokens"] = standard_logging_object.get("completion_tokens")

        from llm_gateway.callbacks.prometheus import PrometheusCallback

        with patch.object(PrometheusCallback, "_on_success", capture_on_success):
            with anthropic_client.messages.stream(
                model="claude-3-haiku-20240307",
                messages=[{"role": "user", "content": "Say 'y'"}],
                max_tokens=5,
            ) as stream:
                stream.get_final_text()

        assert received_data.get("prompt_tokens") is not None
        assert received_data.get("completion_tokens") is not None


class TestEndUserIdExtraction:
    pytestmark = pytest.mark.skipif(not OPENAI_API_KEY, reason="OPENAI_API_KEY not set")

    def test_openai_user_param_extracted_as_end_user(self, openai_client: OpenAI) -> None:
        """Verify that the 'user' parameter in OpenAI requests is extracted as end_user_id."""
        received_data: dict[str, object] = {}

        async def capture_on_success(self, kwargs, response_obj, start_time, end_time, end_user_id):
            received_data["end_user_id"] = end_user_id
            received_data["user_in_kwargs"] = kwargs.get("user")

        from llm_gateway.callbacks.rate_limiting import RateLimitCallback

        with patch.object(RateLimitCallback, "_on_success", capture_on_success):
            openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Say 'test'"}],
                max_tokens=5,
                user="test-end-user-123",
            )

        assert received_data.get("end_user_id") == "test-end-user-123"
        assert received_data.get("user_in_kwargs") == "test-end-user-123"

    def test_openai_request_without_user_param(self, openai_client: OpenAI) -> None:
        """Verify that requests without 'user' parameter have no end_user_id."""
        received_data: dict[str, str | None] = {}

        async def capture_on_success(self, kwargs, response_obj, start_time, end_time, end_user_id):
            received_data["end_user_id"] = end_user_id

        from llm_gateway.callbacks.rate_limiting import RateLimitCallback

        with patch.object(RateLimitCallback, "_on_success", capture_on_success):
            openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": "Say 'test'"}],
                max_tokens=5,
            )

        assert received_data.get("end_user_id") is None
