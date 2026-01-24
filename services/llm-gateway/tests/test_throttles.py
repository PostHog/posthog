from __future__ import annotations

import pytest

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.config import get_settings
from llm_gateway.rate_limiting.cost_throttles import ProductCostThrottle, UserCostThrottle
from llm_gateway.rate_limiting.runner import ThrottleRunner
from llm_gateway.rate_limiting.throttles import (
    Throttle,
    ThrottleContext,
    ThrottleResult,
    get_team_multiplier,
)


def make_user(
    user_id: int = 1,
    team_id: int | None = 1,
    auth_method: str = "personal_api_key",
    scopes: list[str] | None = None,
    application_id: str | None = None,
) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        team_id=team_id,
        auth_method=auth_method,
        distinct_id=f"test-distinct-id-{user_id}",
        scopes=scopes or ["llm_gateway:read"],
        application_id=application_id,
    )


def make_context(
    user: AuthenticatedUser | None = None,
    product: str = "llm_gateway",
    request_id: str | None = None,
) -> ThrottleContext:
    return ThrottleContext(
        user=user or make_user(),
        product=product,
        request_id=request_id,
    )


class TestThrottleResult:
    def test_allow_creates_allowed_result(self) -> None:
        result = ThrottleResult.allow()
        assert result.allowed is True

    def test_deny_creates_denied_result_with_defaults(self) -> None:
        result = ThrottleResult.deny()
        assert result.allowed is False
        assert result.status_code == 429
        assert result.detail == "Rate limit exceeded"

    def test_deny_with_custom_status_code(self) -> None:
        result = ThrottleResult.deny(status_code=403)
        assert result.allowed is False
        assert result.status_code == 403

    def test_deny_with_custom_detail(self) -> None:
        result = ThrottleResult.deny(detail="Access denied")
        assert result.detail == "Access denied"

    def test_deny_with_scope(self) -> None:
        result = ThrottleResult.deny(scope="global_burst")
        assert result.scope == "global_burst"


class TestThrottleRunner:
    @pytest.mark.asyncio
    async def test_allows_when_all_throttles_allow(self) -> None:
        class AlwaysAllowThrottle(Throttle):
            scope = "always_allow"

            async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
                return ThrottleResult.allow()

        runner = ThrottleRunner(throttles=[AlwaysAllowThrottle(), AlwaysAllowThrottle()])
        context = make_context()

        result = await runner.check(context)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_first_failure_wins(self) -> None:
        class FirstThrottle(Throttle):
            scope = "first"

            async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
                return ThrottleResult.deny(status_code=403, detail="First denied", scope="first")

        class SecondThrottle(Throttle):
            scope = "second"

            async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
                return ThrottleResult.deny(status_code=429, detail="Second denied", scope="second")

        runner = ThrottleRunner(throttles=[FirstThrottle(), SecondThrottle()])
        context = make_context()

        result = await runner.check(context)
        assert result.allowed is False
        assert result.status_code == 403
        assert result.detail == "First denied"
        assert result.scope == "first"

    @pytest.mark.asyncio
    async def test_runs_all_throttles_in_parallel(self) -> None:
        call_count = 0

        class CountingThrottle(Throttle):
            scope = "counting"

            async def allow_request(self, context: ThrottleContext) -> ThrottleResult:
                nonlocal call_count
                call_count += 1
                return ThrottleResult.deny()

        runner = ThrottleRunner(throttles=[CountingThrottle(), CountingThrottle(), CountingThrottle()])
        context = make_context()

        await runner.check(context)
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_empty_throttle_list_allows_all(self) -> None:
        runner = ThrottleRunner(throttles=[])
        context = make_context()

        result = await runner.check(context)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_composite_cost_throttle_order(self) -> None:
        product_throttle = ProductCostThrottle(redis=None)
        user_throttle = UserCostThrottle(redis=None)

        runner = ThrottleRunner(throttles=[product_throttle, user_throttle])

        user = make_user(auth_method="personal_api_key")
        context = make_context(user=user, product="llm_gateway")

        result = await runner.check(context)
        assert result.allowed is True


class TestThrottleContext:
    def test_context_holds_user_and_product(self) -> None:
        user = make_user(user_id=42)
        context = ThrottleContext(user=user, product="wizard")

        assert context.user.user_id == 42
        assert context.product == "wizard"

    def test_context_holds_request_id(self) -> None:
        context = ThrottleContext(
            user=make_user(),
            product="llm_gateway",
            request_id="req-123",
        )

        assert context.request_id == "req-123"


class TestGetTeamMultiplier:
    def test_returns_1_for_none_team_id(self) -> None:
        assert get_team_multiplier(None) == 1

    def test_returns_1_for_unconfigured_team(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", '{"2": 10}')
        get_settings.cache_clear()
        assert get_team_multiplier(99) == 1
        get_settings.cache_clear()

    def test_returns_configured_multiplier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", '{"2": 10, "5": 5}')
        get_settings.cache_clear()
        assert get_team_multiplier(2) == 10
        assert get_team_multiplier(5) == 5
        get_settings.cache_clear()
