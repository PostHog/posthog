import json
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.callbacks.posthog import (
    _MAX_CAPTURE_SIZE,
    PostHogCallback,
    _normalize_trace_id,
    _replace_binary_content,
    _truncate_for_capture,
)


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except ValueError:
        return False


def _run_sync(executor, fn, *args):
    """Execute the function synchronously, bypassing the thread pool for tests."""
    fn(*args)


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

    @pytest.fixture
    def mock_posthog_client(self):
        mock_client = MagicMock()
        with patch("llm_gateway.callbacks.posthog.Posthog", return_value=mock_client) as mock_cls:
            yield mock_cls, mock_client

    @pytest.fixture(autouse=True)
    def mock_event_loop(self):
        mock_loop = MagicMock()
        mock_loop.run_in_executor.side_effect = _run_sync
        with patch("llm_gateway.callbacks.posthog.asyncio") as mock_asyncio:
            mock_asyncio.get_running_loop.return_value = mock_loop
            yield mock_loop

    @pytest.mark.asyncio
    async def test_on_success_captures_event(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        mock_cls, mock_client = mock_posthog_client
        kwargs = {
            "standard_logging_object": standard_logging_object,
            "litellm_params": {},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="wizard"),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            mock_cls.assert_called_once_with(
                "test-key", host="https://test.posthog.com", sync_mode=True, enable_local_evaluation=False
            )
            mock_client.capture.assert_called_once()
            call_kwargs = mock_client.capture.call_args.kwargs

            assert call_kwargs["distinct_id"] == "user-distinct-id-123"
            assert call_kwargs["event"] == "$ai_generation"
            assert call_kwargs["groups"] == {"instance": "https://us.posthog.com", "project": 456}

            props = call_kwargs["properties"]
            assert props["$ai_model"] == "claude-3-opus"
            assert props["$ai_provider"] == "anthropic"
            assert props["$ai_input_tokens"] == 10
            assert props["$ai_output_tokens"] == 20
            assert props["$ai_latency"] == 1.5
            assert props["$ai_total_cost_usd"] == 0.05
            assert props["team_id"] == 456
            assert props["ai_product"] == "wizard"
            mock_client.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_success_stamps_effort_from_context(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="posthog_code"),
            patch("llm_gateway.callbacks.posthog.get_effort", return_value="medium"),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_client.capture.call_args.kwargs["properties"]
            assert props["$ai_effort"] == "medium"

    @pytest.mark.asyncio
    async def test_on_success_omits_effort_when_absent(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="posthog_code"),
            patch("llm_gateway.callbacks.posthog.get_effort", return_value=None),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_client.capture.call_args.kwargs["properties"]
            assert "$ai_effort" not in props

    @pytest.mark.asyncio
    async def test_on_failure_stamps_effort_from_context(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser, mock_posthog_client: tuple
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {
            "standard_logging_object": {
                "model": "claude-3-opus",
                "custom_llm_provider": "anthropic",
                "error_str": "boom",
            },
            "litellm_params": {},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="posthog_code"),
            patch("llm_gateway.callbacks.posthog.get_effort", return_value="high"),
        ):
            await callback._on_failure(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_client.capture.call_args.kwargs["properties"]
            assert props["$ai_effort"] == "high"

    @pytest.mark.asyncio
    async def test_on_success_effort_overrides_caller_header(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        # $ai_effort is gateway-owned: a caller-supplied x-posthog-property-$ai_effort
        # must not win over the value the gateway resolved from the request body.
        _, mock_client = mock_posthog_client
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="posthog_code"),
            patch("llm_gateway.callbacks.posthog.get_effort", return_value="medium"),
            patch("llm_gateway.callbacks.posthog.get_posthog_properties", return_value={"$ai_effort": "spoofed"}),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_client.capture.call_args.kwargs["properties"]
            assert props["$ai_effort"] == "medium"

    @pytest.mark.asyncio
    async def test_on_success_drops_caller_effort_when_gateway_has_none(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        # With no gateway-resolved effort, a caller-supplied value is dropped rather than
        # captured — the property is owned by the gateway, not spoofable via a header.
        _, mock_client = mock_posthog_client
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="posthog_code"),
            patch("llm_gateway.callbacks.posthog.get_effort", return_value=None),
            patch("llm_gateway.callbacks.posthog.get_posthog_properties", return_value={"$ai_effort": "spoofed"}),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_client.capture.call_args.kwargs["properties"]
            assert "$ai_effort" not in props

    @pytest.mark.asyncio
    async def test_on_failure_drops_caller_effort_when_gateway_has_none(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser, mock_posthog_client: tuple
    ) -> None:
        # Same spoof-prevention as the success path applies to error events.
        _, mock_client = mock_posthog_client
        kwargs = {
            "standard_logging_object": {
                "model": "claude-3-opus",
                "custom_llm_provider": "anthropic",
                "error_str": "boom",
            },
            "litellm_params": {},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="posthog_code"),
            patch("llm_gateway.callbacks.posthog.get_effort", return_value=None),
            patch("llm_gateway.callbacks.posthog.get_posthog_properties", return_value={"$ai_effort": "spoofed"}),
        ):
            await callback._on_failure(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_client.capture.call_args.kwargs["properties"]
            assert "$ai_effort" not in props

    @pytest.mark.asyncio
    async def test_on_success_header_team_id_overrides_auth_user_team(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        """A caller-supplied x-posthog-property-team_id wins over the key owner's team.

        This is how a shared-key caller (e.g. signals) attributes a generation to the
        customer team rather than the key owner's team that the usage reporter reads.
        """
        _, mock_client = mock_posthog_client
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="signals"),
            # headers arrive as strings — this is the realistic x-posthog-property-team_id path
            patch("llm_gateway.callbacks.posthog.get_posthog_properties", return_value={"team_id": "999"}),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            call_kwargs = mock_client.capture.call_args.kwargs
            props = call_kwargs["properties"]
            # header-supplied customer team wins over auth_user.team_id (456), stored as an int
            assert props["team_id"] == 999
            assert isinstance(props["team_id"], int)
            # the analytics project the event lands in still follows the authenticated team
            assert call_kwargs["groups"] == {"instance": "https://us.posthog.com", "project": 456}

    @pytest.mark.asyncio
    async def test_on_success_invalid_header_team_id_falls_back_to_auth_team(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="signals"),
            patch("llm_gateway.callbacks.posthog.get_posthog_properties", return_value={"team_id": "not-a-number"}),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_client.capture.call_args.kwargs["properties"]
            assert props["team_id"] == 456
            assert isinstance(props["team_id"], int)

    @pytest.mark.asyncio
    async def test_on_success_invalid_header_team_id_dropped_without_auth_team(
        self,
        callback: PostHogCallback,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=None),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="signals"),
            patch("llm_gateway.callbacks.posthog.get_posthog_properties", return_value={"team_id": "not-a-number"}),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_client.capture.call_args.kwargs["properties"]
            assert "team_id" not in props

    @pytest.mark.asyncio
    async def test_on_success_headers_cannot_override_ai_product_or_billable(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        """ai_product and $ai_billable are gateway-owned: caller headers can't override them.

        Otherwise a typo'd header would silently mis-bill or misattribute the generation.
        """
        _, mock_client = mock_posthog_client
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="posthog_code"),
            patch(
                "llm_gateway.callbacks.posthog.get_posthog_properties",
                return_value={"ai_product": "spoofed", "$ai_billable": True},
            ),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_client.capture.call_args.kwargs["properties"]
            # route-derived product wins over the header value
            assert props["ai_product"] == "posthog_code"
            # config-derived billable flag wins (posthog_code is non-billable)
            assert props["$ai_billable"] is False

    @pytest.mark.asyncio
    async def test_on_success_uses_uuid_when_no_auth_user(
        self,
        callback: PostHogCallback,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=None),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="llm_gateway"),
            patch("llm_gateway.callbacks.posthog.uuid4", return_value=MagicMock(hex="test-uuid")),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            call_kwargs = mock_client.capture.call_args.kwargs
            # distinct_id should be a UUID string since no auth user.
            # The instance group is always set so the destination project can
            # resolve $group_<N> for the region URL filter in the usage report,
            # even when no authenticated team is known.
            assert call_kwargs["groups"] == {"instance": "https://us.posthog.com"}

    @pytest.mark.asyncio
    async def test_on_success_uses_end_user_id_for_distinct_id(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {
            "standard_logging_object": standard_logging_object,
            "litellm_params": {"metadata": {"user_id": "trace-id-123"}},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="llm_gateway"),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id="end-user-123")

            call_kwargs = mock_client.capture.call_args.kwargs
            assert call_kwargs["distinct_id"] == "end-user-123"

            props = call_kwargs["properties"]
            assert props["$ai_trace_id"] == _normalize_trace_id("trace-id-123")
            assert _is_uuid(props["$ai_trace_id"])

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method_name", ["_on_success", "_on_failure"])
    async def test_oauth_uses_auth_user_distinct_id_not_end_user_id(
        self, callback: PostHogCallback, method_name: str, mock_posthog_client: tuple
    ) -> None:
        _, mock_client = mock_posthog_client
        oauth_user = AuthenticatedUser(
            user_id=123,
            team_id=456,
            auth_method="oauth_access_token",
            distinct_id="real-posthog-distinct-id",
        )
        kwargs = {
            "standard_logging_object": {
                "model": "claude-3-opus",
                "custom_llm_provider": "anthropic",
                "messages": [{"role": "user", "content": "Hello"}],
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "response_time": 1.5,
                "response_cost": 0.05,
                "response": "Hi",
            },
            "litellm_params": {},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=oauth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="wizard"),
        ):
            method = getattr(callback, method_name)
            await method(kwargs, None, 0.0, 1.0, end_user_id="123")

            call_kwargs = mock_client.capture.call_args.kwargs
            assert call_kwargs["distinct_id"] == "real-posthog-distinct-id"

    @pytest.mark.asyncio
    async def test_on_failure_captures_error_event(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser, mock_posthog_client: tuple
    ) -> None:
        _, mock_client = mock_posthog_client
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
            patch("llm_gateway.callbacks.posthog.get_product", return_value="posthog_code"),
        ):
            await callback._on_failure(kwargs, None, 0.0, 1.0, end_user_id=None)

            mock_client.capture.assert_called_once()
            call_kwargs = mock_client.capture.call_args.kwargs

            assert call_kwargs["distinct_id"] == "user-distinct-id-123"
            assert call_kwargs["event"] == "$ai_generation"

            props = call_kwargs["properties"]
            assert props["$ai_model"] == "claude-3-opus"
            assert props["$ai_is_error"] is True
            assert props["$ai_error"] == "Rate limit exceeded"
            assert props["ai_product"] == "posthog_code"
            mock_client.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_success_without_optional_fields(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser, mock_posthog_client: tuple
    ) -> None:
        _, mock_client = mock_posthog_client
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
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_client.capture.call_args.kwargs["properties"]
            assert props["$ai_input_tokens"] == 0
            assert props["$ai_output_tokens"] == 0
            assert "$ai_total_cost_usd" not in props
            assert "$ai_output_choices" not in props

    def test_callback_name_is_posthog(self, callback: PostHogCallback) -> None:
        assert callback.callback_name == "posthog"

    @pytest.mark.asyncio
    async def test_on_success_emits_cache_tokens_when_present(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser, mock_posthog_client: tuple
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {
            "standard_logging_object": {
                "model": "claude-sonnet-4-6",
                "custom_llm_provider": "anthropic",
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "metadata": {
                    "usage_object": {
                        "cache_read_input_tokens": 60,
                        "cache_creation_input_tokens": 30,
                    },
                },
            },
            "litellm_params": {},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="slack_app"),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

        props = mock_client.capture.call_args.kwargs["properties"]
        assert props["$ai_cache_read_input_tokens"] == 60
        assert props["$ai_cache_creation_input_tokens"] == 30

    @pytest.mark.asyncio
    async def test_on_success_omits_cache_tokens_when_absent(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="slack_app"),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

        props = mock_client.capture.call_args.kwargs["properties"]
        assert "$ai_cache_read_input_tokens" not in props
        assert "$ai_cache_creation_input_tokens" not in props

    @pytest.mark.parametrize(
        "cost_breakdown,expected_props",
        [
            pytest.param(
                {
                    "input_cost": 0.003,
                    "cache_read_cost": 0.001,
                    "cache_creation_cost": 0.002,
                    "output_cost": 0.006,
                    "total_cost": 0.012,
                },
                {
                    "$ai_input_cost_usd": 0.003,
                    "$ai_output_cost_usd": 0.006,
                    "$ai_cache_read_cost_usd": 0.001,
                    "$ai_cache_creation_cost_usd": 0.002,
                },
                id="anthropic_with_cache",
            ),
            pytest.param(
                {"input_cost": 0.02, "output_cost": 0.03},
                {"$ai_input_cost_usd": 0.02, "$ai_output_cost_usd": 0.03},
                id="no_cache_components",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_on_success_emits_cost_breakdown(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        mock_posthog_client: tuple,
        cost_breakdown: dict,
        expected_props: dict,
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {
            "standard_logging_object": {
                "model": "claude-sonnet-4-6",
                "custom_llm_provider": "anthropic",
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "response_cost": cost_breakdown.get("total_cost"),
                "cost_breakdown": cost_breakdown,
            },
            "litellm_params": {},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="slack_app"),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

        props = mock_client.capture.call_args.kwargs["properties"]
        # Each LiteLLM cost_breakdown component maps 1:1 to its own PostHog
        # property — disjoint, so the sum reconciles to $ai_total_cost_usd.
        for key, value in expected_props.items():
            assert props[key] == value
        for key in ("$ai_cache_read_cost_usd", "$ai_cache_creation_cost_usd"):
            if key not in expected_props:
                assert key not in props

    @pytest.mark.asyncio
    async def test_on_success_omits_per_side_cost_when_breakdown_absent(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="slack_app"),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

        props = mock_client.capture.call_args.kwargs["properties"]
        assert "$ai_input_cost_usd" not in props
        assert "$ai_output_cost_usd" not in props
        assert "$ai_cache_read_cost_usd" not in props
        assert "$ai_cache_creation_cost_usd" not in props

    @pytest.mark.asyncio
    async def test_on_success_emits_reasoning_tokens_when_present(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser, mock_posthog_client: tuple
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {
            "standard_logging_object": {
                "model": "gpt-5.2",
                "custom_llm_provider": "openai",
                "prompt_tokens": 50,
                "completion_tokens": 200,
                "metadata": {
                    "usage_object": {
                        "completion_tokens_details": {"reasoning_tokens": 120},
                    },
                },
            },
            "litellm_params": {},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="slack_app_routing"),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

        props = mock_client.capture.call_args.kwargs["properties"]
        assert props["$ai_reasoning_tokens"] == 120

    @pytest.mark.asyncio
    async def test_on_success_omits_reasoning_tokens_when_absent(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="slack_app"),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

        props = mock_client.capture.call_args.kwargs["properties"]
        assert "$ai_reasoning_tokens" not in props

    @pytest.mark.asyncio
    @pytest.mark.parametrize("product", ["wizard", "posthog_code", "llm_gateway"])
    async def test_on_success_includes_ai_product(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        product: str,
        mock_posthog_client: tuple,
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {
            "standard_logging_object": standard_logging_object,
            "litellm_params": {},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value=product),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_client.capture.call_args.kwargs["properties"]
            assert props["ai_product"] == product

    @pytest.mark.asyncio
    @pytest.mark.parametrize("product", ["wizard", "posthog_code", "llm_gateway"])
    async def test_on_failure_includes_ai_product(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser, product: str, mock_posthog_client: tuple
    ) -> None:
        _, mock_client = mock_posthog_client
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
        ):
            await callback._on_failure(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_client.capture.call_args.kwargs["properties"]
            assert props["ai_product"] == product

    @pytest.mark.asyncio
    @pytest.mark.parametrize("product", ["slack_app", "slack_app_routing"])
    async def test_on_success_marks_slack_products_billable(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        product: str,
        mock_posthog_client: tuple,
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value=product),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

        props = mock_client.capture.call_args.kwargs["properties"]
        assert props["$ai_billable"] is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("product", ["posthog_code", "background_agents", "wizard", "llm_gateway"])
    async def test_on_success_does_not_mark_other_products_billable(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        product: str,
        mock_posthog_client: tuple,
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value=product),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

        props = mock_client.capture.call_args.kwargs["properties"]
        assert props["$ai_billable"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("product", ["slack_app", "slack_app_routing"])
    async def test_on_failure_marks_slack_products_billable(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        mock_posthog_client: tuple,
        product: str,
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {
            "standard_logging_object": {
                "model": "claude-sonnet-4-6",
                "custom_llm_provider": "anthropic",
                "error_str": "boom",
            },
            "litellm_params": {},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value=product),
        ):
            await callback._on_failure(kwargs, None, 0.0, 1.0, end_user_id=None)

        props = mock_client.capture.call_args.kwargs["properties"]
        assert props["$ai_billable"] is True

    @pytest.mark.asyncio
    async def test_on_success_uses_passed_end_user_id(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        _, mock_client = mock_posthog_client
        kwargs = {
            "standard_logging_object": standard_logging_object,
            "litellm_params": {"metadata": {"user_id": "metadata-user-id"}},
        }

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="growth"),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id="openai-end-user-456")

            call_kwargs = mock_client.capture.call_args.kwargs
            assert call_kwargs["distinct_id"] == "openai-end-user-456"
            assert call_kwargs["groups"] == {"instance": "https://us.posthog.com", "project": 456}

            props = call_kwargs["properties"]
            assert props["$ai_trace_id"] == _normalize_trace_id("metadata-user-id")
            assert _is_uuid(props["$ai_trace_id"])

    @pytest.mark.asyncio
    async def test_on_failure_uses_passed_end_user_id(
        self, callback: PostHogCallback, auth_user: AuthenticatedUser, mock_posthog_client: tuple
    ) -> None:
        _, mock_client = mock_posthog_client
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
        ):
            await callback._on_failure(kwargs, None, 0.0, 1.0, end_user_id="openai-end-user-789")

            call_kwargs = mock_client.capture.call_args.kwargs
            assert call_kwargs["distinct_id"] == "openai-end-user-789"
            assert call_kwargs["properties"]["$ai_trace_id"] == _normalize_trace_id("trace-id-from-metadata")
            assert _is_uuid(call_kwargs["properties"]["$ai_trace_id"])

    @pytest.mark.asyncio
    async def test_on_success_uses_configured_region_url_in_groups(
        self,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        _, mock_client = mock_posthog_client
        callback = PostHogCallback(
            api_key="eu-key",
            host="https://eu.i.posthog.com",
            region_url="https://eu.posthog.com",
        )
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="slack_app"),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

        call_kwargs = mock_client.capture.call_args.kwargs
        assert call_kwargs["groups"] == {"instance": "https://eu.posthog.com", "project": 456}
        # $group_1 is stamped explicitly so the usage-report query's hardcoded
        # filter matches regardless of how the destination team registers
        # `instance` in GroupTypeMapping.
        assert call_kwargs["properties"]["$group_1"] == "https://eu.posthog.com"

    @pytest.mark.asyncio
    async def test_on_success_mirrors_to_secondary_destination_when_configured(
        self,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
    ) -> None:
        mock_client = MagicMock()
        with patch("llm_gateway.callbacks.posthog.Posthog", return_value=mock_client) as mock_cls:
            callback = PostHogCallback(
                api_key="eu-key",
                host="https://eu.i.posthog.com",
                region_url="https://eu.posthog.com",
                secondary_api_key="us-key",
                secondary_host="https://us.i.posthog.com",
            )
            kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

            with (
                patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
                patch("llm_gateway.callbacks.posthog.get_product", return_value="slack_app"),
            ):
                await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            # One Posthog client constructed per destination, each captured once.
            primary_call, secondary_call = mock_cls.call_args_list
            assert primary_call.args == ("eu-key",)
            assert primary_call.kwargs["host"] == "https://eu.i.posthog.com"
            assert secondary_call.args == ("us-key",)
            assert secondary_call.kwargs["host"] == "https://us.i.posthog.com"
            assert mock_client.capture.call_count == 2

            # Both copies carry the EU origin region — via the SDK `groups` arg
            # and via an explicit $group_1 property — so the US-region usage
            # report filter ($group_1 = 'https://us.posthog.com') excludes the
            # mirrored copy and does not double-count.
            for capture_call in mock_client.capture.call_args_list:
                assert capture_call.kwargs["groups"] == {
                    "instance": "https://eu.posthog.com",
                    "project": 456,
                }
                assert capture_call.kwargs["properties"]["$group_1"] == "https://eu.posthog.com"

    @pytest.mark.asyncio
    async def test_on_success_skips_secondary_destination_when_unconfigured(
        self,
        callback: PostHogCallback,
        auth_user: AuthenticatedUser,
        standard_logging_object: dict,
        mock_posthog_client: tuple,
    ) -> None:
        mock_cls, mock_client = mock_posthog_client
        kwargs = {"standard_logging_object": standard_logging_object, "litellm_params": {}}

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="slack_app"),
        ):
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

        assert mock_cls.call_count == 1
        assert mock_client.capture.call_count == 1

    @pytest.mark.asyncio
    async def test_on_failure_mirrors_to_secondary_destination_when_configured(
        self,
        auth_user: AuthenticatedUser,
    ) -> None:
        mock_client = MagicMock()
        with patch("llm_gateway.callbacks.posthog.Posthog", return_value=mock_client) as mock_cls:
            callback = PostHogCallback(
                api_key="eu-key",
                host="https://eu.i.posthog.com",
                region_url="https://eu.posthog.com",
                secondary_api_key="us-key",
                secondary_host="https://us.i.posthog.com",
            )
            kwargs = {
                "standard_logging_object": {
                    "model": "claude-sonnet-4-6",
                    "custom_llm_provider": "anthropic",
                    "error_str": "boom",
                },
                "litellm_params": {},
            }

            with (
                patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
                patch("llm_gateway.callbacks.posthog.get_product", return_value="slack_app"),
            ):
                await callback._on_failure(kwargs, None, 0.0, 1.0, end_user_id=None)

            primary_call, secondary_call = mock_cls.call_args_list
            assert primary_call.args == ("eu-key",)
            assert primary_call.kwargs["host"] == "https://eu.i.posthog.com"
            assert secondary_call.args == ("us-key",)
            assert secondary_call.kwargs["host"] == "https://us.i.posthog.com"
            assert mock_client.capture.call_count == 2

            for capture_call in mock_client.capture.call_args_list:
                assert capture_call.kwargs["groups"] == {
                    "instance": "https://eu.posthog.com",
                    "project": 456,
                }
                assert capture_call.kwargs["properties"]["$group_1"] == "https://eu.posthog.com"
                assert capture_call.kwargs["properties"]["$ai_is_error"] is True


class TestNormalizeTraceId:
    def test_returns_fresh_uuid_when_value_is_falsy(self) -> None:
        falsy_inputs: list[Any] = [None, "", 0, []]
        for raw in falsy_inputs:
            value = _normalize_trace_id(raw)
            assert _is_uuid(value)

    def test_returns_fresh_uuids_each_call_when_value_is_falsy(self) -> None:
        assert _normalize_trace_id(None) != _normalize_trace_id(None)

    def test_passes_through_existing_uuid(self) -> None:
        existing = "550e8400-e29b-41d4-a716-446655440000"
        assert _normalize_trace_id(existing) == existing

    def test_hashes_non_uuid_string_deterministically(self) -> None:
        raw = '{"session_id": "abc", "thread_ts": "1.234"}'
        first = _normalize_trace_id(raw)
        second = _normalize_trace_id(raw)
        assert first == second
        assert _is_uuid(first)
        assert first != raw

    def test_distinct_inputs_produce_distinct_uuids(self) -> None:
        assert _normalize_trace_id("trace-a") != _normalize_trace_id("trace-b")

    def test_serializes_dict_input_with_stable_key_order(self) -> None:
        first = _normalize_trace_id({"a": 1, "b": 2})
        second = _normalize_trace_id({"b": 2, "a": 1})
        assert first == second
        assert _is_uuid(first)


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


_MAX_SIZE = _MAX_CAPTURE_SIZE
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

    def test_threshold_below_kafka_message_limit(self) -> None:
        # Capture rejects events over Kafka's message.max.bytes (~1 MB) with a 413,
        # so the truncation threshold must stay under it with headroom for the envelope.
        assert _MAX_CAPTURE_SIZE < 1_000_000

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
        mock_client = MagicMock()
        callback = PostHogCallback(api_key="test-key", host="https://test.posthog.com")
        auth_user = AuthenticatedUser(user_id=123, team_id=456, auth_method="personal_api_key", distinct_id="user-123")
        large_response = "R" * (16 * 1024 * 1024)
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

        mock_loop = MagicMock()
        mock_loop.run_in_executor.side_effect = _run_sync

        with (
            patch("llm_gateway.callbacks.posthog.get_auth_user", return_value=auth_user),
            patch("llm_gateway.callbacks.posthog.get_product", return_value="wizard"),
            patch("llm_gateway.callbacks.posthog.Posthog", return_value=mock_client),
            patch("llm_gateway.callbacks.posthog.asyncio") as mock_asyncio,
        ):
            mock_asyncio.get_running_loop.return_value = mock_loop
            await callback._on_success(kwargs, None, 0.0, 1.0, end_user_id=None)

            props = mock_client.capture.call_args.kwargs["properties"]
            assert props["$ai_output_choices"] == _TRUNCATION_MARKER
            assert props["$ai_model"] == "claude-3-opus"
            assert props["$ai_input_tokens"] == 10
            assert props["$ai_output_tokens"] == 50000
            assert props["$ai_total_cost_usd"] == 1.23
            assert props["$ai_latency"] == 2.5
            assert len(json.dumps(props)) < _MAX_SIZE
