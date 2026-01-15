from __future__ import annotations

import pytest

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.rate_limiting.model_throttles import (
    ProductModelInputTokenThrottle,
    UserModelInputTokenThrottle,
)
from llm_gateway.rate_limiting.runner import ThrottleRunner
from llm_gateway.rate_limiting.throttles import (
    Throttle,
    ThrottleContext,
    ThrottleResult,
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
        scopes=scopes or ["llm_gateway:read"],
        application_id=application_id,
    )


def make_context(
    user: AuthenticatedUser | None = None,
    product: str = "llm_gateway",
    model: str | None = None,
    input_tokens: int | None = None,
    max_output_tokens: int | None = None,
    request_id: str | None = None,
) -> ThrottleContext:
    return ThrottleContext(
        user=user or make_user(),
        product=product,
        model=model,
        input_tokens=input_tokens,
        max_output_tokens=max_output_tokens,
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
    async def test_composite_throttle_order(self) -> None:
        product_throttle = ProductModelInputTokenThrottle(redis=None)
        user_throttle = UserModelInputTokenThrottle(redis=None)

        runner = ThrottleRunner(throttles=[product_throttle, user_throttle])

        user = make_user(auth_method="personal_api_key")
        context = make_context(
            user=user,
            product="llm_gateway",
            model="claude-3-5-haiku",
            input_tokens=100,
        )

        result = await runner.check(context)
        assert result.allowed is True


class TestThrottleContext:
    def test_context_holds_user_and_product(self) -> None:
        user = make_user(user_id=42)
        context = ThrottleContext(user=user, product="wizard")

        assert context.user.user_id == 42
        assert context.product == "wizard"

    def test_context_holds_model_info(self) -> None:
        context = ThrottleContext(
            user=make_user(),
            product="llm_gateway",
            model="claude-3-5-sonnet",
            input_tokens=1000,
            max_output_tokens=4096,
            request_id="req-123",
        )

        assert context.model == "claude-3-5-sonnet"
        assert context.input_tokens == 1000
        assert context.max_output_tokens == 4096
        assert context.request_id == "req-123"
