import pytest

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.config import get_settings
from llm_gateway.rate_limiting.model_cost_service import ModelCostService, get_model_limits
from llm_gateway.rate_limiting.model_throttles import (
    ProductModelInputTokenThrottle,
    ProductModelOutputTokenThrottle,
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

    async def test_product_uses_10x_limit(self) -> None:
        product_throttle = ProductModelInputTokenThrottle(redis=None)
        user_throttle = UserModelInputTokenThrottle(redis=None)

        assert product_throttle.limit_multiplier == 10
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
    async def test_allows_when_under_limit(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)
        context = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=1000,
        )

        result = await throttle.allow_request(context)
        assert result.allowed is True

    async def test_skips_when_no_tokens_in_context(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)
        context = make_context(model="claude-3-5-haiku-20241022", max_output_tokens=None)

        result = await throttle.allow_request(context)
        assert result.allowed is True

    async def test_skips_when_no_model_in_context(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)
        context = make_context(model=None, max_output_tokens=1000)

        result = await throttle.allow_request(context)
        assert result.allowed is True

    async def test_product_uses_10x_limit(self) -> None:
        product_throttle = ProductModelOutputTokenThrottle(redis=None)
        user_throttle = UserModelOutputTokenThrottle(redis=None)

        assert product_throttle.limit_multiplier == 10
        assert user_throttle.limit_multiplier == 1

    async def test_denies_over_limit(self) -> None:
        """Output throttle checks against max_tokens, records actual tokens post-response."""
        throttle = UserModelOutputTokenThrottle(redis=None)
        limits = get_model_limits("claude-3-5-haiku-20241022")
        fallback_limit = limits["output_tph"] // 10

        context = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=fallback_limit,
        )
        # First check passes (check-only, doesn't consume)
        result = await throttle.allow_request(context)
        assert result.allowed is True

        # Record actual usage (this consumes tokens)
        await throttle.record_output_tokens(context, fallback_limit)

        # Now check should fail because we used the full limit
        result = await throttle.allow_request(context)
        assert result.allowed is False
        assert result.scope == "user_model_output_tokens"

    async def test_multiple_requests_record_actual_tokens(self) -> None:
        """Multiple requests record their actual output tokens."""
        throttle = UserModelOutputTokenThrottle(redis=None)
        limits = get_model_limits("claude-3-5-haiku-20241022")
        fallback_limit = limits["output_tph"] // 10
        third = fallback_limit // 3

        ctx = make_context(model="claude-3-5-haiku-20241022", max_output_tokens=third)

        # Check allows (check-only)
        result = await throttle.allow_request(ctx)
        assert result.allowed is True
        await throttle.record_output_tokens(ctx, third)

        result = await throttle.allow_request(ctx)
        assert result.allowed is True
        await throttle.record_output_tokens(ctx, third)

        result = await throttle.allow_request(ctx)
        assert result.allowed is True
        await throttle.record_output_tokens(ctx, third)

        # Fourth request should fail - we've used 3/3 of the limit
        result = await throttle.allow_request(ctx)
        assert result.allowed is False

    async def test_different_models_have_separate_limits(self) -> None:
        throttle = UserModelOutputTokenThrottle(redis=None)

        haiku_limits = get_model_limits("claude-3-5-haiku-20241022")
        haiku_fallback = haiku_limits["output_tph"] // 10

        ctx_haiku = make_context(
            model="claude-3-5-haiku-20241022",
            max_output_tokens=haiku_fallback,
        )
        result = await throttle.allow_request(ctx_haiku)
        assert result.allowed is True

        ctx_opus = make_context(
            model="claude-3-opus-20240229",
            max_output_tokens=1000,
        )
        result = await throttle.allow_request(ctx_opus)
        assert result.allowed is True

    async def test_product_and_user_throttles_track_separately(self) -> None:
        """Product and user throttles have separate buckets."""
        product_throttle = ProductModelOutputTokenThrottle(redis=None)
        user_throttle = UserModelOutputTokenThrottle(redis=None)

        limits = get_model_limits("claude-3-5-haiku-20241022")
        user_fallback = limits["output_tph"] // 10

        user = make_user(user_id=1)

        ctx = make_context(
            user=user,
            model="claude-3-5-haiku-20241022",
            max_output_tokens=user_fallback,
        )

        # Both throttles allow initially (check-only)
        result = await product_throttle.allow_request(ctx)
        assert result.allowed is True
        result = await user_throttle.allow_request(ctx)
        assert result.allowed is True

        # Record tokens to user throttle only (simulating user-scoped consumption)
        await user_throttle.record_output_tokens(ctx, user_fallback)

        ctx2 = make_context(
            user=user,
            model="claude-3-5-haiku-20241022",
            max_output_tokens=1000,
        )
        # Product throttle still has capacity
        result = await product_throttle.allow_request(ctx2)
        assert result.allowed is True
        # User throttle is exhausted
        result = await user_throttle.allow_request(ctx2)
        assert result.allowed is False


class TestProductThrottles:
    async def test_product_input_scope(self) -> None:
        throttle = ProductModelInputTokenThrottle(redis=None)
        assert throttle.scope == "product_model_input_tokens"

    async def test_product_output_scope(self) -> None:
        throttle = ProductModelOutputTokenThrottle(redis=None)
        assert throttle.scope == "product_model_output_tokens"

    async def test_product_cache_key_format(self) -> None:
        throttle = ProductModelInputTokenThrottle(redis=None)
        context = make_context(model="claude-3-5-haiku-20241022", product="wizard")

        key = throttle._get_cache_key(context)
        assert key == "product:wizard:model:claude-3-5-haiku-20241022:input"


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


class TestTeamRateLimitMultipliers:
    async def test_cache_key_has_no_suffix_for_default_multiplier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", "{}")
        get_settings.cache_clear()

        throttle = UserModelInputTokenThrottle(redis=None)
        user = make_user(user_id=1, team_id=99)
        context = make_context(user=user, model="claude-3-5-haiku-20241022")

        key = throttle._get_cache_key(context)
        assert ":tm" not in key
        assert key == "user:1:model:claude-3-5-haiku-20241022:input"
        get_settings.cache_clear()

    async def test_cache_key_includes_multiplier_suffix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", '{"2": 10}')
        get_settings.cache_clear()

        throttle = UserModelInputTokenThrottle(redis=None)
        user = make_user(user_id=1, team_id=2)
        context = make_context(user=user, model="claude-3-5-haiku-20241022")

        key = throttle._get_cache_key(context)
        assert key == "user:1:model:claude-3-5-haiku-20241022:input:tm10"
        get_settings.cache_clear()

    async def test_product_cache_key_includes_multiplier_suffix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", '{"2": 10}')
        get_settings.cache_clear()

        throttle = ProductModelInputTokenThrottle(redis=None)
        user = make_user(user_id=1, team_id=2)
        context = make_context(user=user, model="claude-3-5-haiku-20241022", product="wizard")

        key = throttle._get_cache_key(context)
        assert key == "product:wizard:model:claude-3-5-haiku-20241022:input:tm10"
        get_settings.cache_clear()

    async def test_team_with_multiplier_gets_higher_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", '{"2": 10}')
        get_settings.cache_clear()

        throttle = UserModelInputTokenThrottle(redis=None)
        limits = get_model_limits("claude-3-5-haiku-20241022")
        base_fallback_limit = limits["input_tph"] // 10

        user_with_multiplier = make_user(user_id=1, team_id=2)
        context = make_context(
            user=user_with_multiplier,
            model="claude-3-5-haiku-20241022",
            input_tokens=base_fallback_limit,
        )

        result = await throttle.allow_request(context)
        assert result.allowed is True

        result = await throttle.allow_request(context)
        assert result.allowed is True, "Should allow 2x the base limit with 10x multiplier"

        get_settings.cache_clear()

    async def test_team_without_multiplier_uses_default_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", '{"2": 10}')
        get_settings.cache_clear()

        throttle = UserModelInputTokenThrottle(redis=None)
        limits = get_model_limits("claude-3-5-haiku-20241022")
        fallback_limit = limits["input_tph"] // 10

        user_no_multiplier = make_user(user_id=2, team_id=99)
        context = make_context(
            user=user_no_multiplier,
            model="claude-3-5-haiku-20241022",
            input_tokens=fallback_limit,
        )

        result = await throttle.allow_request(context)
        assert result.allowed is True

        result = await throttle.allow_request(context)
        assert result.allowed is False, "Should deny after exceeding base limit"

        get_settings.cache_clear()
