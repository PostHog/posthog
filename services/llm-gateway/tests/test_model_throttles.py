import pytest

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.rate_limiting.model_throttles import (
    GlobalModelInputTokenThrottle,
    GlobalModelOutputTokenThrottle,
    UserModelInputTokenThrottle,
    UserModelOutputTokenThrottle,
    get_model_limits,
)
from llm_gateway.rate_limiting.throttles import ThrottleContext


def make_user(user_id: int = 1, team_id: int = 1) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        team_id=team_id,
        auth_method="personal_api_key",
        scopes=["llm_gateway:read"],
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


class TestGetModelLimits:
    @pytest.mark.parametrize(
        "model,expected_input,expected_output",
        [
            ("claude-3-5-haiku-20241022", 4_000_000, 800_000),
            ("claude-3-opus-20240229", 2_000_000, 400_000),
            ("gpt-4o-mini", 4_000_000, 800_000),
            ("gpt-4o", 2_000_000, 400_000),
            ("unknown-model-xyz", 500_000, 100_000),  # Default expensive
        ],
    )
    def test_model_limits(self, model: str, expected_input: int, expected_output: int) -> None:
        limits = get_model_limits(model)
        assert limits["input_tpm"] == expected_input
        assert limits["output_tpm"] == expected_output


class TestInputTokenThrottle:
    async def test_allows_when_under_limit(self) -> None:
        throttle = UserModelInputTokenThrottle(redis=None)
        context = make_context(
            model="claude-3-5-haiku",
            input_tokens=100,
        )

        result = await throttle.allow_request(context)
        assert result.allowed is True

    async def test_skips_when_no_tokens_in_context(self) -> None:
        throttle = UserModelInputTokenThrottle(redis=None)
        context = make_context(model="claude-3-5-haiku", input_tokens=None)

        result = await throttle.allow_request(context)
        assert result.allowed is True

    async def test_skips_when_no_model_in_context(self) -> None:
        throttle = UserModelInputTokenThrottle(redis=None)
        context = make_context(model=None, input_tokens=100)

        result = await throttle.allow_request(context)
        assert result.allowed is True

    async def test_global_uses_10x_limit(self) -> None:
        global_throttle = GlobalModelInputTokenThrottle(redis=None)
        user_throttle = UserModelInputTokenThrottle(redis=None)

        # Both are using fallback (limit/10)
        # Global: 4M * 10 / 10 = 4M
        # User: 4M / 10 = 400K

        assert global_throttle.limit_multiplier == 10
        assert user_throttle.limit_multiplier == 1

    async def test_denies_over_limit(self) -> None:
        throttle = UserModelInputTokenThrottle(redis=None)
        # Fallback limit is 4M/10 = 400K tokens
        # Consume all at once
        context = make_context(
            model="claude-3-5-haiku",
            input_tokens=400_000,
        )
        result = await throttle.allow_request(context)
        assert result.allowed is True

        # Next request should be denied
        result = await throttle.allow_request(context)
        assert result.allowed is False
        assert result.scope == "user_model_input_tokens"


class TestOutputTokenThrottle:
    async def test_reserves_max_tokens(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)
        context = make_context(
            model="claude-3-5-haiku",
            max_output_tokens=1000,
            request_id="req-123",
        )

        result = await throttle.allow_request(context)
        assert result.allowed is True
        assert "req-123" in throttle._reservations

    async def test_adjust_releases_unused(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)
        context = make_context(
            model="claude-3-5-haiku",
            max_output_tokens=1000,
            request_id="req-123",
        )

        await throttle.allow_request(context)
        assert "req-123" in throttle._reservations

        # Adjust with actual usage (200 tokens used)
        await throttle.adjust_after_response("req-123", 200)

        # Reservation should be removed
        assert "req-123" not in throttle._reservations

    async def test_adjust_noop_when_no_reservation(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)

        # Should not raise
        await throttle.adjust_after_response("nonexistent-req", 100)

    async def test_multiple_concurrent_requests(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)

        ctx1 = make_context(
            model="claude-3-5-haiku",
            max_output_tokens=1000,
            request_id="req-1",
        )
        ctx2 = make_context(
            model="claude-3-5-haiku",
            max_output_tokens=2000,
            request_id="req-2",
        )

        await throttle.allow_request(ctx1)
        await throttle.allow_request(ctx2)

        assert "req-1" in throttle._reservations
        assert "req-2" in throttle._reservations

        # Adjust first, second should remain
        await throttle.adjust_after_response("req-1", 500)
        assert "req-1" not in throttle._reservations
        assert "req-2" in throttle._reservations


class TestGlobalThrottles:
    async def test_global_input_scope(self) -> None:
        throttle = GlobalModelInputTokenThrottle(redis=None)
        assert throttle.scope == "global_model_input_tokens"

    async def test_global_output_scope(self) -> None:
        throttle = GlobalModelOutputTokenThrottle(redis=None)
        assert throttle.scope == "global_model_output_tokens"

    async def test_global_cache_key_format(self) -> None:
        throttle = GlobalModelInputTokenThrottle(redis=None)
        context = make_context(model="claude-3-5-haiku")

        key = throttle._get_cache_key(context)
        assert key == "global:model:claude-3-5-haiku:input"


class TestUserThrottles:
    async def test_user_input_scope(self) -> None:
        throttle = UserModelInputTokenThrottle(redis=None)
        assert throttle.scope == "user_model_input_tokens"

    async def test_user_output_scope(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)
        assert throttle.scope == "user_model_output_tokens"

    async def test_user_cache_key_includes_user_id(self) -> None:
        throttle = UserModelInputTokenThrottle(redis=None)
        user = make_user(user_id=42)
        context = make_context(user=user, model="claude-3-5-haiku")

        key = throttle._get_cache_key(context)
        assert key == "user:42:model:claude-3-5-haiku:input"
