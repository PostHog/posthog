from unittest.mock import AsyncMock, MagicMock

import pytest

from llm_gateway.rate_limiting.throttles import ThrottleContext
from llm_gateway.request_context import (
    RequestContext,
    apply_posthog_context_from_headers,
    get_posthog_flags,
    get_posthog_properties,
    get_posthog_trace_id,
    record_cost,
    request_context_var,
    set_request_context,
    set_throttle_context,
    throttle_context_var,
    throttle_runner_var,
)


def make_mock_user() -> MagicMock:
    user = MagicMock()
    user.user_id = 1
    user.team_id = 1
    user.application_id = None
    user.auth_method = "api_key"
    return user


def make_mock_request(headers: list[tuple[str, str]]) -> MagicMock:
    """Mock a Starlette request whose headers support items() and case-insensitive get()."""
    lowered = {name.lower(): value for name, value in headers}
    request = MagicMock()
    request.headers = MagicMock()
    request.headers.items.return_value = headers
    request.headers.get.side_effect = lambda name, default=None: lowered.get(name.lower(), default)
    return request


class TestRecordCost:
    @pytest.fixture(autouse=True)
    def reset_context_vars(self) -> None:
        throttle_runner_var.set(None)
        throttle_context_var.set(None)

    async def test_record_cost_calls_runner(self) -> None:
        mock_runner = MagicMock()
        mock_runner.record_cost = AsyncMock()

        context = ThrottleContext(
            user=make_mock_user(),
            product="llm_gateway",
        )

        set_throttle_context(mock_runner, context)

        await record_cost(0.0015)

        mock_runner.record_cost.assert_called_once_with(context, 0.0015)

    async def test_record_cost_no_op_without_context(self) -> None:
        await record_cost(0.0015)

    async def test_record_cost_no_op_with_partial_context(self) -> None:
        mock_runner = MagicMock()
        throttle_runner_var.set(mock_runner)

        await record_cost(0.0015)

        mock_runner.record_cost.assert_not_called()

    async def test_record_cost_does_not_override_existing_end_user_id(self) -> None:
        mock_runner = MagicMock()
        mock_runner.record_cost = AsyncMock()

        context = ThrottleContext(
            user=make_mock_user(),
            product="llm_gateway",
            end_user_id="authenticated-user-42",
        )

        set_throttle_context(mock_runner, context)

        await record_cost(0.0015, end_user_id="attacker-supplied-id")

        assert context.end_user_id == "authenticated-user-42"
        mock_runner.record_cost.assert_called_once_with(context, 0.0015)

    async def test_record_cost_sets_end_user_id_when_not_already_set(self) -> None:
        mock_runner = MagicMock()
        mock_runner.record_cost = AsyncMock()

        context = ThrottleContext(
            user=make_mock_user(),
            product="llm_gateway",
            end_user_id=None,
        )

        set_throttle_context(mock_runner, context)

        await record_cost(0.0015, end_user_id="fallback-id")

        assert context.end_user_id == "fallback-id"
        mock_runner.record_cost.assert_called_once_with(context, 0.0015)


class TestApplyPosthogContextFromHeaders:
    @pytest.fixture(autouse=True)
    def reset_request_context(self) -> None:
        request_context_var.set(None)

    def test_sets_properties_and_flags_from_headers(self) -> None:
        request = make_mock_request(
            [
                ("X-POSTHOG-PROPERTY-VARIANT", "memes"),
                ("X-POSTHOG-FLAG-EXPERIMENT", "test"),
                ("Content-Type", "application/json"),
            ]
        )
        set_request_context(RequestContext(request_id="req-123"))

        apply_posthog_context_from_headers(request)

        assert get_posthog_properties() == {"variant": "memes"}
        assert get_posthog_flags() == {"experiment": "test"}

    def test_leaves_existing_context_unchanged_without_matching_headers(self) -> None:
        request = make_mock_request([("Content-Type", "application/json")])
        set_request_context(
            RequestContext(
                request_id="req-123",
                posthog_properties={"existing": "property"},
                posthog_flags={"existing": "flag"},
            )
        )

        apply_posthog_context_from_headers(request)

        assert get_posthog_properties() == {"existing": "property"}
        assert get_posthog_flags() == {"existing": "flag"}

    def test_updates_only_properties_preserves_existing_flags(self) -> None:
        request = make_mock_request(
            [
                ("X-POSTHOG-PROPERTY-VARIANT", "memes"),
                ("Content-Type", "application/json"),
            ]
        )
        set_request_context(
            RequestContext(
                request_id="req-123",
                posthog_properties={"existing": "property"},
                posthog_flags={"existing": "flag"},
            )
        )

        apply_posthog_context_from_headers(request)

        assert get_posthog_properties() == {"variant": "memes"}
        assert get_posthog_flags() == {"existing": "flag"}

    def test_updates_only_flags_preserves_existing_properties(self) -> None:
        request = make_mock_request(
            [
                ("X-POSTHOG-FLAG-EXPERIMENT", "test"),
                ("Content-Type", "application/json"),
            ]
        )
        set_request_context(
            RequestContext(
                request_id="req-123",
                posthog_properties={"existing": "property"},
                posthog_flags={"existing": "flag"},
            )
        )

        apply_posthog_context_from_headers(request)

        assert get_posthog_properties() == {"existing": "property"}
        assert get_posthog_flags() == {"experiment": "test"}

    def test_passes_through_dollar_prefixed_property_keys(self) -> None:
        # `$`-prefixed keys the gateway does not derive (e.g. `$ai_span_name`) are
        # legitimate caller enrichment and must survive extraction; the capture
        # callback protects derived keys via a setdefault merge, not by stripping here.
        request = make_mock_request(
            [
                ("X-POSTHOG-PROPERTY-$ai_span_name", "slack_nudge_classifier"),
                ("X-POSTHOG-PROPERTY-team_id", "42"),
                ("X-POSTHOG-PROPERTY-ai_stage", "draft"),
            ]
        )
        set_request_context(RequestContext(request_id="req-123"))

        apply_posthog_context_from_headers(request)

        assert get_posthog_properties() == {
            "$ai_span_name": "slack_nudge_classifier",
            "team_id": "42",
            "ai_stage": "draft",
        }

    def test_sets_trace_id_from_header(self) -> None:
        request = make_mock_request([("X-PostHog-Trace-Id", "0e3c1c81-8bcc-40d8-9e28-1ed92b3a7c3a")])
        set_request_context(RequestContext(request_id="req-123"))

        apply_posthog_context_from_headers(request)

        assert get_posthog_trace_id() == "0e3c1c81-8bcc-40d8-9e28-1ed92b3a7c3a"

    def test_accepts_trace_id_header_at_length_cap(self) -> None:
        at_cap = "x" * 256
        request = make_mock_request([("X-PostHog-Trace-Id", at_cap)])
        set_request_context(RequestContext(request_id="req-123"))

        apply_posthog_context_from_headers(request)

        assert get_posthog_trace_id() == at_cap

    def test_trims_surrounding_whitespace_from_trace_id_header(self) -> None:
        request = make_mock_request([("X-PostHog-Trace-Id", "  0e3c1c81-8bcc-40d8-9e28-1ed92b3a7c3a  ")])
        set_request_context(RequestContext(request_id="req-123"))

        apply_posthog_context_from_headers(request)

        assert get_posthog_trace_id() == "0e3c1c81-8bcc-40d8-9e28-1ed92b3a7c3a"

    def test_trace_id_absent_without_header(self) -> None:
        request = make_mock_request([("Content-Type", "application/json")])
        set_request_context(RequestContext(request_id="req-123"))

        apply_posthog_context_from_headers(request)

        assert get_posthog_trace_id() is None

    @pytest.mark.parametrize("value", ["", "   ", "x" * 257])
    def test_trace_id_blank_or_oversized_header_treated_as_absent(self, value: str) -> None:
        request = make_mock_request([("X-PostHog-Trace-Id", value)])
        set_request_context(RequestContext(request_id="req-123"))

        apply_posthog_context_from_headers(request)

        assert get_posthog_trace_id() is None
