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
            ("gemini-2.5-flash-lite", 4_000_000, 800_000),
            ("gemini-2.5-flash", 4_000_000, 800_000),
            ("gemini-2.5-pro", 2_000_000, 400_000),
            ("gemini-2.0-flash", 4_000_000, 800_000),
            ("gemini-3-flash-preview", 4_000_000, 800_000),
            ("gemini-3-pro-preview", 2_000_000, 400_000),
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


class TestOutputTokenAdjustment:
    """Tests verifying that released tokens restore capacity for future requests."""

    async def test_released_tokens_allow_subsequent_requests(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)
        # Fallback limit: 800K / 10 = 80K tokens

        # Reserve all capacity
        ctx1 = make_context(
            model="claude-3-5-haiku",
            max_output_tokens=80_000,
            request_id="req-1",
        )
        result = await throttle.allow_request(ctx1)
        assert result.allowed is True

        # Next request should be denied (capacity exhausted)
        ctx2 = make_context(
            model="claude-3-5-haiku",
            max_output_tokens=1000,
            request_id="req-2",
        )
        result = await throttle.allow_request(ctx2)
        assert result.allowed is False

        # Adjust first request - only used 1000 tokens, release 79000
        await throttle.adjust_after_response("req-1", 1000)

        # Now the same request should succeed
        result = await throttle.allow_request(ctx2)
        assert result.allowed is True

    async def test_exact_usage_releases_nothing(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)
        # Fallback limit: 80K tokens

        # Reserve 40K
        ctx1 = make_context(
            model="claude-3-5-haiku",
            max_output_tokens=40_000,
            request_id="req-1",
        )
        await throttle.allow_request(ctx1)

        # Reserve another 40K (at limit now)
        ctx2 = make_context(
            model="claude-3-5-haiku",
            max_output_tokens=40_000,
            request_id="req-2",
        )
        await throttle.allow_request(ctx2)

        # Third request should be denied
        ctx3 = make_context(
            model="claude-3-5-haiku",
            max_output_tokens=1000,
            request_id="req-3",
        )
        result = await throttle.allow_request(ctx3)
        assert result.allowed is False

        # Adjust first request with exact usage (no release)
        await throttle.adjust_after_response("req-1", 40_000)

        # Third request should still be denied
        result = await throttle.allow_request(ctx3)
        assert result.allowed is False

    async def test_over_usage_does_not_break(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)

        ctx = make_context(
            model="claude-3-5-haiku",
            max_output_tokens=1000,
            request_id="req-1",
        )
        await throttle.allow_request(ctx)

        # Edge case: actual > reserved (shouldn't happen but handle gracefully)
        await throttle.adjust_after_response("req-1", 2000)

        # Reservation should be removed, no crash
        assert "req-1" not in throttle._reservations

    async def test_partial_release_restores_partial_capacity(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)
        # Fallback limit: 80K tokens

        # Reserve all capacity
        ctx1 = make_context(
            model="claude-3-5-haiku",
            max_output_tokens=80_000,
            request_id="req-1",
        )
        await throttle.allow_request(ctx1)

        # Release half (used 40K, release 40K)
        await throttle.adjust_after_response("req-1", 40_000)

        # Should allow a 40K request now
        ctx2 = make_context(
            model="claude-3-5-haiku",
            max_output_tokens=40_000,
            request_id="req-2",
        )
        result = await throttle.allow_request(ctx2)
        assert result.allowed is True

        # But not another 40K (only 40K was released)
        ctx3 = make_context(
            model="claude-3-5-haiku",
            max_output_tokens=40_000,
            request_id="req-3",
        )
        result = await throttle.allow_request(ctx3)
        assert result.allowed is False

    async def test_adjustment_is_model_specific(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)

        # Reserve all haiku capacity
        ctx_haiku = make_context(
            model="claude-3-5-haiku",
            max_output_tokens=80_000,
            request_id="req-haiku",
        )
        await throttle.allow_request(ctx_haiku)

        # Opus should have its own capacity (40K fallback for opus)
        ctx_opus = make_context(
            model="claude-3-opus",
            max_output_tokens=40_000,
            request_id="req-opus",
        )
        result = await throttle.allow_request(ctx_opus)
        assert result.allowed is True

        # Release haiku tokens
        await throttle.adjust_after_response("req-haiku", 1000)

        # Haiku should now have capacity again
        ctx_haiku2 = make_context(
            model="claude-3-5-haiku",
            max_output_tokens=79_000,
            request_id="req-haiku-2",
        )
        result = await throttle.allow_request(ctx_haiku2)
        assert result.allowed is True

    async def test_global_and_user_throttles_track_separately(self) -> None:
        global_throttle = GlobalModelOutputTokenThrottle(redis=None)
        user_throttle = UserModelOutputTokenThrottle(redis=None)

        # Global limit: 800K * 10 / 10 = 800K
        # User limit: 800K / 10 = 80K

        user = make_user(user_id=1)

        # User reserves all their capacity
        ctx = make_context(
            user=user,
            model="claude-3-5-haiku",
            max_output_tokens=80_000,
            request_id="req-1",
        )

        # Both should allow
        result = await global_throttle.allow_request(ctx)
        assert result.allowed is True
        result = await user_throttle.allow_request(ctx)
        assert result.allowed is True

        # User is at limit, global is not
        ctx2 = make_context(
            user=user,
            model="claude-3-5-haiku",
            max_output_tokens=1000,
            request_id="req-2",
        )
        result = await global_throttle.allow_request(ctx2)
        assert result.allowed is True
        result = await user_throttle.allow_request(ctx2)
        assert result.allowed is False

        # Adjust user throttle
        await user_throttle.adjust_after_response("req-1", 1000)

        # Now user should have capacity
        result = await user_throttle.allow_request(ctx2)
        assert result.allowed is True


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
