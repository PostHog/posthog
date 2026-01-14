import pytest

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.rate_limiting.model_cost_service import ModelCostService, get_model_limits
from llm_gateway.rate_limiting.model_throttles import (
    GlobalModelInputTokenThrottle,
    GlobalModelOutputTokenThrottle,
    UserModelInputTokenThrottle,
    UserModelOutputTokenThrottle,
)
from llm_gateway.rate_limiting.throttles import ThrottleContext


@pytest.fixture(autouse=True)
def reset_model_cost_service():
    ModelCostService.reset_instance()
    yield
    ModelCostService.reset_instance()


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


class TestInputTokenThrottle:
    async def test_allows_when_under_limit(self) -> None:
        throttle = UserModelInputTokenThrottle(redis=None)
        context = make_context(
            model="claude-3-5-haiku-20241022",
            input_tokens=100,
        )

        result = await throttle.allow_request(context)
        assert result.allowed is True

    async def test_skips_when_no_tokens_in_context(self) -> None:
        throttle = UserModelInputTokenThrottle(redis=None)
        context = make_context(model="claude-3-5-haiku-20241022", input_tokens=None)

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

        assert global_throttle.limit_multiplier == 10
        assert user_throttle.limit_multiplier == 1

    async def test_denies_over_limit(self) -> None:
        throttle = UserModelInputTokenThrottle(redis=None)
        limits = get_model_limits("claude-3-5-haiku-20241022")
        fallback_limit = limits["input_tph"] // 10

        context = make_context(
            model="claude-3-5-haiku-20241022",
            input_tokens=fallback_limit,
        )
        result = await throttle.allow_request(context)
        assert result.allowed is True

        result = await throttle.allow_request(context)
        assert result.allowed is False
        assert result.scope == "user_model_input_tokens"


class TestOutputTokenThrottle:
    async def test_reserves_max_tokens(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)
        context = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=1000,
            request_id="req-123",
        )

        result = await throttle.allow_request(context)
        assert result.allowed is True
        assert "req-123" in throttle._reservations

    async def test_adjust_releases_unused(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)
        context = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=1000,
            request_id="req-123",
        )

        await throttle.allow_request(context)
        assert "req-123" in throttle._reservations

        await throttle.adjust_after_response("req-123", 200)

        assert "req-123" not in throttle._reservations

    async def test_adjust_noop_when_no_reservation(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)

        await throttle.adjust_after_response("nonexistent-req", 100)

    async def test_multiple_concurrent_requests(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)

        ctx1 = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=1000,
            request_id="req-1",
        )
        ctx2 = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=2000,
            request_id="req-2",
        )

        await throttle.allow_request(ctx1)
        await throttle.allow_request(ctx2)

        assert "req-1" in throttle._reservations
        assert "req-2" in throttle._reservations

        await throttle.adjust_after_response("req-1", 500)
        assert "req-1" not in throttle._reservations
        assert "req-2" in throttle._reservations


class TestOutputTokenAdjustment:
    """Tests verifying that released tokens restore capacity for future requests."""

    async def test_released_tokens_allow_subsequent_requests(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)
        limits = get_model_limits("claude-3-5-haiku-20241022")
        fallback_limit = limits["output_tph"] // 10

        ctx1 = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=fallback_limit,
            request_id="req-1",
        )
        result = await throttle.allow_request(ctx1)
        assert result.allowed is True

        ctx2 = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=1000,
            request_id="req-2",
        )
        result = await throttle.allow_request(ctx2)
        assert result.allowed is False

        await throttle.adjust_after_response("req-1", 1000)

        result = await throttle.allow_request(ctx2)
        assert result.allowed is True

    async def test_exact_usage_releases_nothing(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)
        limits = get_model_limits("claude-3-5-haiku-20241022")
        fallback_limit = limits["output_tph"] // 10
        half_limit = fallback_limit // 2

        ctx1 = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=half_limit,
            request_id="req-1",
        )
        await throttle.allow_request(ctx1)

        ctx2 = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=half_limit,
            request_id="req-2",
        )
        await throttle.allow_request(ctx2)

        ctx3 = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=1000,
            request_id="req-3",
        )
        result = await throttle.allow_request(ctx3)
        assert result.allowed is False

        await throttle.adjust_after_response("req-1", half_limit)

        result = await throttle.allow_request(ctx3)
        assert result.allowed is False

    async def test_over_usage_does_not_break(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)

        ctx = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=1000,
            request_id="req-1",
        )
        await throttle.allow_request(ctx)

        await throttle.adjust_after_response("req-1", 2000)

        assert "req-1" not in throttle._reservations

    async def test_partial_release_restores_partial_capacity(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)
        limits = get_model_limits("claude-3-5-haiku-20241022")
        fallback_limit = limits["output_tph"] // 10
        half_limit = fallback_limit // 2

        ctx1 = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=fallback_limit,
            request_id="req-1",
        )
        await throttle.allow_request(ctx1)

        await throttle.adjust_after_response("req-1", half_limit)

        ctx2 = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=half_limit,
            request_id="req-2",
        )
        result = await throttle.allow_request(ctx2)
        assert result.allowed is True

        ctx3 = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=half_limit,
            request_id="req-3",
        )
        result = await throttle.allow_request(ctx3)
        assert result.allowed is False

    async def test_adjustment_is_model_specific(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)

        haiku_limits = get_model_limits("claude-3-5-haiku-20241022")
        haiku_fallback = haiku_limits["output_tph"] // 10

        opus_limits = get_model_limits("claude-3-opus-20240229")
        opus_fallback = opus_limits["output_tph"] // 10

        ctx_haiku = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=haiku_fallback,
            request_id="req-haiku",
        )
        await throttle.allow_request(ctx_haiku)

        ctx_opus = make_context(
            model="claude-3-opus-20240229",
            max_output_tokens=opus_fallback // 2,
            request_id="req-opus",
        )
        result = await throttle.allow_request(ctx_opus)
        assert result.allowed is True

        await throttle.adjust_after_response("req-haiku", 1000)

        ctx_haiku2 = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=haiku_fallback - 1000,
            request_id="req-haiku-2",
        )
        result = await throttle.allow_request(ctx_haiku2)
        assert result.allowed is True

    async def test_global_and_user_throttles_track_separately(self) -> None:
        global_throttle = GlobalModelOutputTokenThrottle(redis=None)
        user_throttle = UserModelOutputTokenThrottle(redis=None)

        limits = get_model_limits("claude-3-5-haiku-20241022")
        user_fallback = limits["output_tph"] // 10

        user = make_user(user_id=1)

        ctx = make_context(
            user=user,
            model="claude-3-5-haiku-20241022",
            max_output_tokens=user_fallback,
            request_id="req-1",
        )

        result = await global_throttle.allow_request(ctx)
        assert result.allowed is True
        result = await user_throttle.allow_request(ctx)
        assert result.allowed is True

        ctx2 = make_context(
            user=user,
            model="claude-3-5-haiku-20241022",
            max_output_tokens=1000,
            request_id="req-2",
        )
        result = await global_throttle.allow_request(ctx2)
        assert result.allowed is True
        result = await user_throttle.allow_request(ctx2)
        assert result.allowed is False

        await user_throttle.adjust_after_response("req-1", 1000)

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
        context = make_context(model="claude-3-5-haiku-20241022")

        key = throttle._get_cache_key(context)
        assert key == "global:model:claude-3-5-haiku-20241022:input"


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
        context = make_context(user=user, model="claude-3-5-haiku-20241022")

        key = throttle._get_cache_key(context)
        assert key == "user:42:model:claude-3-5-haiku-20241022:input"
