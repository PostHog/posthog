import json
from unittest.mock import MagicMock, patch

import pytest

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.callbacks.posthog import PostHogCallback, _replace_binary_content, _truncate_for_capture


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
            "litellm_params": {},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="wizard"),
            patch("llm_gateway.callbacks.posthog.posthoganalytics") as mock_posthog,
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            mock_posthog.capture.assert_called_once()
            call_kwargs = mock_posthog.capture.call_args.kwargs

            assert call_kwargs["distinct_id"] == "user-distinct-id-123"
            assert call_kwargs["event"] == "$ai_generation"
            assert call_kwargs["groups"] == {"project": 456}

            props = call_kwargs["properties"]
            assert props["$ai_model"] == "claude-3-opus"
            assert props["$ai_provider"] == "anthropic"
            assert props["$ai_input_tokens"] == 10
            assert props["$ai_output_tokens"] == 20
            assert props["$ai_latency"] == 1.5
            assert props["$ai_total_cost_usd"] == 0.05
            assert props["team_id"] == 456
            assert props["ai_product"] == "wizard"
            mock_posthog.flush.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_success_uses_uuid_when_no_auth_user(
        self, callback: PostHogCallback, standard_logging_object: dict
    ) -> None:
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=None),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="llm_gateway"),
            patch("llm_gateway.callbacks.posthog.posthoganalytics") as mock_posthog,
            patch("llm_gateway.callbacks.posthog.uuid4", return_value=MagicMock(hex="test-uuid")),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            call_kwargs = mock_posthog.capture.call_args.kwargs
            # distinct_id should be a UUID string since no auth user
            assert "groups" not in call_kwargs  # No team_id means no groups

    @pytest.mark.asyncio
    async def test_on_success_uses_end_user_id_for_distinct_id(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser, standard_logging_object: dict
    ) -> None:
        kwargs = {
            "standard_logging_object": standard_logging_object,
            "litellm_params": {"metadata": {"user_id": "trace-id-123"}},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="llm_gateway"),
            patch("llm_gateway.callbacks.posthog.posthoganalytics") as mock_posthog,
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id="end-user-123")

            call_kwargs = mock_posthog.capture.call_args.kwargs
            assert call_kwargs["distinct_id"] == "end-user-123"

            props = call_kwargs["properties"]
            assert props["$ai_trace_id"] == "trace-id-123"

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
            "litellm_params": {},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="twig"),
            patch("llm_gateway.callbacks.posthog.posthoganalytics") as mock_posthog,
        ):
            await callback._on_failure(kwargs, None, 0.0, 1.0, end_user_id=None)

            mock_posthog.capture.assert_called_once()
            call_kwargs = mock_posthog.capture.call_args.kwargs

            assert call_kwargs["distinct_id"] == "user-distinct-id-123"
            assert call_kwargs["event"] == "$ai_generation"

            props = call_kwargs["properties"]
            assert props["$ai_model"] == "claude-3-opus"
            assert props["$ai_is_error"] is True
            assert props["$ai_error"] == "Rate limit exceeded"
            assert props["ai_product"] == "twig"
            mock_posthog.flush.assert_not_called()

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
            patch("llm_gateway.callbacks.posthog.get_product", return_value="llm_gateway"),
            patch("llm_gateway.callbacks.posthog.posthoganalytics") as mock_posthog,
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_posthog.capture.call_args.kwargs["properties"]
            assert props["$ai_input_tokens"] == 0
            assert props["$ai_output_tokens"] == 0
            assert "$ai_total_cost_usd" not in props
            assert "$ai_output_choices" not in props

    def test_callback_name_is_posthog(self, callback: PostHogCallback) -> None:
        assert callback.callback_name == "posthog"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("product", ["wizard", "twig", "llm_gateway"])
    async def test_on_success_includes_ai_product(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser, standard_logging_object: dict, product: str
    ) -> None:
        kwargs = {
            "standard_logging_object": standard_logging_object,
            "litellm_params": {},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value=product),
            patch("llm_gateway.callbacks.posthog.posthoganalytics") as mock_posthog,
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_posthog.capture.call_args.kwargs["properties"]
            assert props["ai_product"] == product

    @pytest.mark.asyncio
    @pytest.mark.parametrize("product", ["wizard", "twig", "llm_gateway"])
    async def test_on_failure_includes_ai_product(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser, product: str
    ) -> None:
        kwargs = {
            "standard_logging_object": {
                "model": "claude-3-opus",
                "custom_llm_provider": "anthropic",
                "error_str": "Error",
            },
            "litellm_params": {},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value=product),
            patch("llm_gateway.callbacks.posthog.posthoganalytics") as mock_posthog,
        ):
            await callback._on_failure(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_posthog.capture.call_args.kwargs["properties"]
            assert props["ai_product"] == product

    @pytest.mark.asyncio
    async def test_on_success_uses_passed_end_user_id(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser, standard_logging_object: dict
    ) -> None:
        kwargs = {
            "standard_logging_object": standard_logging_object,
            "litellm_params": {"metadata": {"user_id": "metadata-user-id"}},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="growth"),
            patch("llm_gateway.callbacks.posthog.posthoganalytics") as mock_posthog,
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id="openai-end-user-456")

            call_kwargs = mock_posthog.capture.call_args.kwargs
            assert call_kwargs["distinct_id"] == "openai-end-user-456"
            assert call_kwargs["groups"] == {"project": 456}

            props = call_kwargs["properties"]
            assert props["$ai_trace_id"] == "metadata-user-id"

    @pytest.mark.asyncio
    async def test_on_failure_uses_passed_end_user_id(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser
    ) -> None:
        kwargs = {
            "standard_logging_object": {
                "model": "gpt-4",
                "custom_llm_provider": "openai",
                "error_str": "Error",
            },
            "litellm_params": {"metadata": {"user_id": "trace-id-from-metadata"}},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="growth"),
            patch("llm_gateway.callbacks.posthog.posthoganalytics") as mock_posthog,
        ):
            await callback._on_failure(kwargs, None, 0.0, 1.0, end_user_id="openai-end-user-789")

            call_kwargs = mock_posthog.capture.call_args.kwargs
            assert call_kwargs["distinct_id"] == "openai-end-user-789"
            assert call_kwargs["properties"]["$ai_trace_id"] == "trace-id-from-metadata"


class TestReplaceBinaryContent:
    @pytest.mark.parametrize(
        "input_data,expected",
        [
            # Primitives pass through unchanged
            (None, None),
            (42, 42),
            (3.14, 3.14),
            (True, True),
            ("hello world", "hello world"),
            # Raw bytes replaced with metadata
            (b"\x00\x00\x00", {"type": "binary", "size_bytes": 3}),
            # Stringified bytes get parsed and replaced
            ("b'\\x00\\x00'", {"type": "binary", "size_bytes": 2}),
            # File tuple (filename, bytes) - bytes replaced, structure preserved
            (
                ("recording.m4a", b"\x00\x00\x00\x00"),
                ("recording.m4a", {"type": "binary", "size_bytes": 4}),
            ),
            # Stringified file tuple - format LiteLLM sends for audio transcription
            (
                "('file.m4a', b'\\x00\\x01\\x02')",
                ("file.m4a", {"type": "binary", "size_bytes": 3}),
            ),
            # Lists with mixed content
            (
                [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}],
                [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}],
            ),
            # List with bytes
            (
                [b"\x00", "text", 123],
                [{"type": "binary", "size_bytes": 1}, "text", 123],
            ),
            # Nested dict with bytes
            (
                {"file": b"content", "name": "test.txt"},
                {"file": {"type": "binary", "size_bytes": 7}, "name": "test.txt"},
            ),
            # Stringified file tuple nested in message list
            (
                [{"role": "user", "content": "('audio.m4a', b'\\x00\\x01\\x02')"}],
                [{"role": "user", "content": ("audio.m4a", {"type": "binary", "size_bytes": 3})}],
            ),
            # Invalid Python literal strings pass through unchanged
            ("not a python literal", "not a python literal"),
            ("Hello, how are you?", "Hello, how are you?"),
        ],
    )
    def test_replace_binary_content(self, input_data, expected):
        assert _replace_binary_content(input_data) == expected


_MAX_SIZE = 800 * 1024
_TRUNCATION_MARKER = "[truncated: content too large for capture]"


class TestTruncateForCapture:
    @pytest.mark.parametrize(
        "description,properties",
        [
            (
                "small event unchanged",
                {
                    "$ai_model": "claude-3-opus",
                    "$ai_input": [{"role": "user", "content": "Hello"}],
                    "$ai_output_choices": "Hi there!",
                    "$ai_input_tokens": 10,
                },
            ),
            (
                "no content fields unchanged",
                {
                    "$ai_model": "gpt-4",
                    "$ai_input_tokens": 100,
                    "$ai_output_tokens": 200,
                },
            ),
        ],
    )
    def test_small_events_not_truncated(self, description: str, properties: dict) -> None:
        result = _truncate_for_capture(properties)
        assert result == properties

    def test_large_output_truncated(self) -> None:
        large_output = "x" * (_MAX_SIZE + 1)
        properties = {
            "$ai_model": "claude-3-opus",
            "$ai_input": [{"role": "user", "content": "short"}],
            "$ai_output_choices": large_output,
            "$ai_input_tokens": 10,
            "$ai_output_tokens": 5000,
        }

        result = _truncate_for_capture(properties)

        assert result["$ai_output_choices"] == _TRUNCATION_MARKER
        assert result["$ai_input"] == [{"role": "user", "content": "short"}]
        assert result["$ai_input_tokens"] == 10
        assert result["$ai_output_tokens"] == 5000
        assert len(json.dumps(result)) < _MAX_SIZE

    def test_both_fields_truncated_when_both_large(self) -> None:
        large_content = "y" * _MAX_SIZE
        properties = {
            "$ai_model": "claude-3-opus",
            "$ai_input": [{"role": "user", "content": large_content}],
            "$ai_output_choices": large_content,
            "$ai_input_tokens": 10,
        }

        result = _truncate_for_capture(properties)

        assert result["$ai_output_choices"] == _TRUNCATION_MARKER
        assert result["$ai_input"] == _TRUNCATION_MARKER
        assert result["$ai_input_tokens"] == 10
        assert len(json.dumps(result)) < _MAX_SIZE

    def test_does_not_mutate_original(self) -> None:
        large_output = "z" * (_MAX_SIZE + 1)
        original_input = [{"role": "user", "content": "hello"}]
        properties = {
            "$ai_input": original_input,
            "$ai_output_choices": large_output,
        }

        result = _truncate_for_capture(properties)

        assert result is not properties
        assert properties["$ai_output_choices"] == large_output
        assert properties["$ai_input"] is original_input

    def test_small_fields_not_truncated_even_if_total_large(self) -> None:
        properties = {
            "$ai_input": "small input",
            "$ai_output_choices": "x" * (_MAX_SIZE + 1),
        }

        result = _truncate_for_capture(properties)

        assert result["$ai_input"] == "small input"
        assert result["$ai_output_choices"] == _TRUNCATION_MARKER

    @pytest.mark.asyncio
    async def test_on_success_truncates_oversized_content(self) -> None:
        callback = PostHogCallback(api_key="test-key", host="https://test.posthog.com")
        auth_user = AuthenticatedUser(user_id=123, team_id=456, auth_method="personal_api_key", distinct_id="user-123")
        large_response = "R" * (900 * 1024)
        kwargs = {
            "standard_logging_object": {
                "model": "claude-3-opus",
                "custom_llm_provider": "anthropic",
                "messages": [{"role": "user", "content": "Hello"}],
                "prompt_tokens": 10,
                "completion_tokens": 50000,
                "response_time": 2.5,
                "response_cost": 1.23,
                "response": large_response,
            },
            "litellm_params": {},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="wizard"),
            patch("llm_gateway.callbacks.posthog.posthoganalytics") as mock_posthog,
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_posthog.capture.call_args.kwargs["properties"]
            assert props["$ai_output_choices"] == _TRUNCATION_MARKER
            assert props["$ai_model"] == "claude-3-opus"
            assert props["$ai_input_tokens"] == 10
            assert props["$ai_output_tokens"] == 50000
            assert props["$ai_total_cost_usd"] == 1.23
            assert props["$ai_latency"] == 2.5
            assert len(json.dumps(props)) < _MAX_SIZE
