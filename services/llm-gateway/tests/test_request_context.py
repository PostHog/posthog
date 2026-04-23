from unittest.mock import AsyncMock, MagicMock

import pytest

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.rate_limiting.throttles import ThrottleContext
from llm_gateway.request_context import (
    InvalidBillingTeamIdError,
    RequestContext,
    apply_posthog_context_from_headers,
    extract_billing_team_id_from_headers,
    get_billing_team_id,
    get_posthog_flags,
    get_posthog_properties,
    record_cost,
    request_context_var,
    set_billing_team_id,
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
        request = MagicMock()
        request.headers = MagicMock()
        request.headers.items.return_value = [
            ("X-POSTHOG-PROPERTY-VARIANT", "memes"),
            ("X-POSTHOG-FLAG-EXPERIMENT", "test"),
            ("Content-Type", "application/json"),
        ]
        set_request_context(RequestContext(request_id="req-123"))

        apply_posthog_context_from_headers(request)

        assert get_posthog_properties() == {"variant": "memes"}
        assert get_posthog_flags() == {"experiment": "test"}

    def test_leaves_existing_context_unchanged_without_matching_headers(self) -> None:
        request = MagicMock()
        request.headers = MagicMock()
        request.headers.items.return_value = [("Content-Type", "application/json")]
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
        request = MagicMock()
        request.headers = MagicMock()
        request.headers.items.return_value = [
            ("X-POSTHOG-PROPERTY-VARIANT", "memes"),
            ("Content-Type", "application/json"),
        ]
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
        request = MagicMock()
        request.headers = MagicMock()
        request.headers.items.return_value = [
            ("X-POSTHOG-FLAG-EXPERIMENT", "test"),
            ("Content-Type", "application/json"),
        ]
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


def _make_user(team_ids: set[int] | None = None) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=1,
        team_id=42,
        auth_method="personal_api_key",
        distinct_id="distinct-1",
        team_ids=frozenset(team_ids or set()),
    )


class TestExtractBillingTeamIdFromHeaders:
    @pytest.fixture(autouse=True)
    def reset_request_context(self) -> None:
        request_context_var.set(None)

    def test_returns_none_when_header_absent(self) -> None:
        request = MagicMock()
        request.headers = {}
        user = _make_user({42, 99})

        assert extract_billing_team_id_from_headers(request, user) is None

    def test_returns_team_id_when_header_present_and_user_has_access(self) -> None:
        request = MagicMock()
        request.headers = {"x-posthog-team-id": "99"}
        user = _make_user({42, 99})

        assert extract_billing_team_id_from_headers(request, user) == 99

    def test_raises_403_when_user_not_member_of_team(self) -> None:
        request = MagicMock()
        request.headers = {"x-posthog-team-id": "999"}
        user = _make_user({42, 99})

        with pytest.raises(InvalidBillingTeamIdError) as exc_info:
            extract_billing_team_id_from_headers(request, user)

        assert exc_info.value.status_code == 403

    def test_raises_403_when_user_has_no_team_ids(self) -> None:
        request = MagicMock()
        request.headers = {"x-posthog-team-id": "42"}
        user = _make_user(set())  # user is not a member of any team (edge case)

        with pytest.raises(InvalidBillingTeamIdError) as exc_info:
            extract_billing_team_id_from_headers(request, user)

        assert exc_info.value.status_code == 403

    @pytest.mark.parametrize(
        "header_value",
        [
            "not-a-number",
            "12.5",
            "",
            "   ",
            "-1",
            "0",
            "12a",
        ],
    )
    def test_raises_400_on_malformed_header(self, header_value: str) -> None:
        request = MagicMock()
        request.headers = {"x-posthog-team-id": header_value}
        user = _make_user({42, 99})

        with pytest.raises(InvalidBillingTeamIdError) as exc_info:
            extract_billing_team_id_from_headers(request, user)

        assert exc_info.value.status_code == 400

    def test_strips_whitespace_around_team_id(self) -> None:
        request = MagicMock()
        request.headers = {"x-posthog-team-id": "  42  "}
        user = _make_user({42, 99})

        assert extract_billing_team_id_from_headers(request, user) == 42


class TestBillingTeamIdContextVar:
    @pytest.fixture(autouse=True)
    def reset_request_context(self) -> None:
        request_context_var.set(None)

    def test_get_billing_team_id_returns_none_without_context(self) -> None:
        assert get_billing_team_id() is None

    def test_set_billing_team_id_is_noop_without_context(self) -> None:
        set_billing_team_id(42)
        assert get_billing_team_id() is None

    def test_set_and_get_billing_team_id(self) -> None:
        set_request_context(RequestContext(request_id="req-1"))
        set_billing_team_id(42)
        assert get_billing_team_id() == 42

    def test_set_billing_team_id_to_none_clears_value(self) -> None:
        set_request_context(RequestContext(request_id="req-1", billing_team_id=42))
        assert get_billing_team_id() == 42
        set_billing_team_id(None)
        assert get_billing_team_id() is None
