from unittest.mock import MagicMock, patch

import pytest

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.callbacks.posthog import PostHogCallback


class TestPostHogCallback:
    @pytest.fixture
    def callback(self):
        return PostHogCallback(api_key="test-key", host="https://test.posthog.com")

    @pytest.fixture
    def auth_user(self):
        return AuthenticatedUser(
            user_id=123,
            team_id=456,
            auth_method="personal_api_key",
            distinct_id="user-distinct-id-123",
        )

    @pytest.fixture
    def standard_logging_object(self):
        return {
            "model": "claude-3-opus",
            "custom_llm_provider": "anthropic",
            "messages": [{"role": "user", "content": "Hello"}],
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "response_time": 1.5,
            "response_cost": 0.05,
            "response": "Hello! How can I help?",
        }

    @pytest.mark.asyncio
    async def test_on_success_captures_event(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser, standard_logging_object: dict
    ) -> None:
        kwargs = {
            "standard_logging_object": standard_logging_object,
            "litellm_params": {"metadata": {"user_id": "session-123"}},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.posthoganalytics") as mock_posthog,
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0)

            mock_posthog.capture.assert_called_once()
            call_kwargs = mock_posthog.capture.call_args.kwargs

            assert call_kwargs["distinct_id"] == "user-distinct-id-123"
            assert call_kwargs["event"] == "$ai_generation"
            assert call_kwargs["groups"] == {"project": "456"}

            props = call_kwargs["properties"]
            assert props["$ai_model"] == "claude-3-opus"
            assert props["$ai_provider"] == "anthropic"
            assert props["$ai_input_tokens"] == 10
            assert props["$ai_output_tokens"] == 20
            assert props["$ai_latency"] == 1.5
            assert props["$ai_trace_id"] == "session-123"
            assert props["$ai_total_cost_usd"] == 0.05
            assert props["team_id"] == "456"

    @pytest.mark.asyncio
    async def test_on_success_uses_uuid_when_no_auth_user(
        self, callback: PostHogCallback, standard_logging_object: dict
    ) -> None:
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=None),
            patch("llm_gateway.callbacks.posthog.posthoganalytics") as mock_posthog,
            patch("llm_gateway.callbacks.posthog.uuid4", return_value=MagicMock(hex="test-uuid")),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0)

            call_kwargs = mock_posthog.capture.call_args.kwargs
            # distinct_id should be a UUID string since no auth user
            assert "groups" not in call_kwargs  # No team_id means no groups

    @pytest.mark.asyncio
    async def test_on_success_uses_metadata_user_id_as_trace_id(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser, standard_logging_object: dict
    ) -> None:
        kwargs = {
            "standard_logging_object": standard_logging_object,
            "litellm_params": {"metadata": {"user_id": "claude-code-session-xyz"}},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.posthoganalytics") as mock_posthog,
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0)

            props = mock_posthog.capture.call_args.kwargs["properties"]
            assert props["$ai_trace_id"] == "claude-code-session-xyz"

    @pytest.mark.asyncio
    async def test_on_failure_captures_error_event(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser
    ) -> None:
        kwargs = {
            "standard_logging_object": {
                "model": "claude-3-opus",
                "custom_llm_provider": "anthropic",
                "error_str": "Rate limit exceeded",
            },
            "litellm_params": {"metadata": {"user_id": "session-456"}},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.posthoganalytics") as mock_posthog,
        ):
            await callback._on_failure(kwargs, None, 0.0, 1.0)

            mock_posthog.capture.assert_called_once()
            call_kwargs = mock_posthog.capture.call_args.kwargs

            assert call_kwargs["distinct_id"] == "user-distinct-id-123"
            assert call_kwargs["event"] == "$ai_generation"

            props = call_kwargs["properties"]
            assert props["$ai_model"] == "claude-3-opus"
            assert props["$ai_is_error"] is True
            assert props["$ai_error"] == "Rate limit exceeded"
            assert props["$ai_trace_id"] == "session-456"

    @pytest.mark.asyncio
    async def test_on_success_without_optional_fields(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser
    ) -> None:
        kwargs = {
            "standard_logging_object": {
                "model": "gpt-4",
                "custom_llm_provider": "openai",
            },
            "litellm_params": {},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.posthoganalytics") as mock_posthog,
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0)

            props = mock_posthog.capture.call_args.kwargs["properties"]
            assert props["$ai_input_tokens"] == 0
            assert props["$ai_output_tokens"] == 0
            assert "$ai_total_cost_usd" not in props
            assert "$ai_output_choices" not in props

    def test_extract_metadata_returns_empty_dict_when_missing(self, callback: PostHogCallback) -> None:
        assert callback._extract_metadata({}) == {}
        assert callback._extract_metadata({"litellm_params": None}) == {}
        assert callback._extract_metadata({"litellm_params": {}}) == {}
        assert callback._extract_metadata({"litellm_params": {"metadata": None}}) == {}

    def test_extract_metadata_returns_metadata(self, callback: PostHogCallback) -> None:
        kwargs = {"litellm_params": {"metadata": {"user_id": "test", "custom": "value"}}}
        assert callback._extract_metadata(kwargs) == {"user_id": "test", "custom": "value"}

    def test_callback_name_is_posthog(self, callback: PostHogCallback) -> None:
        assert callback.callback_name == "posthog"
