import pytest

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.config import get_settings
from llm_gateway.rate_limiting.throttles import ThrottleContext


def make_user(user_id: int = 1, team_id: int = 1) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        team_id=team_id,
        auth_method="personal_api_key",
        distinct_id=f"test-distinct-id-{user_id}",
        scopes=["llm_gateway:read"],
    )


def make_context(
    user: AuthenticatedUser | None = None,
    product: str = "llm_gateway",
) -> ThrottleContext:
    return ThrottleContext(
        user=user or make_user(),
        product=product,
    )


class TestProductCostLimitConfig:
    def test_default_product_cost_limits(self) -> None:
        get_settings.cache_clear()
        settings = get_settings()
        assert "llm_gateway" in settings.product_cost_limits
        assert settings.product_cost_limits["llm_gateway"].limit_usd == 20.0
        assert settings.product_cost_limits["llm_gateway"].window_seconds == 3600

    def test_parses_json_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "LLM_GATEWAY_PRODUCT_COST_LIMITS",
            '{"wizard": {"limit_usd": 100, "window_seconds": 86400}, "array": {"limit_usd": 50, "window_seconds": 14400}}',
        )
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.product_cost_limits["wizard"].limit_usd == 100.0
        assert settings.product_cost_limits["wizard"].window_seconds == 86400
        assert settings.product_cost_limits["array"].limit_usd == 50.0
        assert settings.product_cost_limits["array"].window_seconds == 14400
        get_settings.cache_clear()

    def test_default_user_cost_settings(self) -> None:
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.default_user_cost_limit_usd == 2.0
        assert settings.default_user_cost_window_seconds == 3600


class TestProductCostThrottle:
    @pytest.mark.asyncio
    async def test_allows_when_under_limit(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import ProductCostThrottle

        throttle = ProductCostThrottle(redis=None)
        context = make_context(product="llm_gateway")

        result = await throttle.allow_request(context)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_denies_when_over_limit(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import ProductCostThrottle

        throttle = ProductCostThrottle(redis=None)
        context = make_context(product="llm_gateway")

        await throttle.record_cost(context, 20.0)

        result = await throttle.allow_request(context)
        assert result.allowed is False
        assert result.scope == "product_cost"
        assert result.detail == "Product rate limit exceeded"

    @pytest.mark.asyncio
    async def test_different_products_have_separate_limits(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import ProductCostThrottle

        throttle = ProductCostThrottle(redis=None)

        ctx_wizard = make_context(product="wizard")
        ctx_array = make_context(product="array")

        await throttle.record_cost(ctx_wizard, 20.0)

        result_wizard = await throttle.allow_request(ctx_wizard)
        result_array = await throttle.allow_request(ctx_array)

        assert result_wizard.allowed is False
        assert result_array.allowed is True

    @pytest.mark.asyncio
    async def test_cache_key_format(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import ProductCostThrottle

        throttle = ProductCostThrottle(redis=None)
        context = make_context(product="wizard")

        key = throttle._get_cache_key(context)
        assert key == "cost:product:wizard"


class TestUserCostThrottle:
    @pytest.mark.asyncio
    async def test_allows_when_under_limit(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import UserCostThrottle

        throttle = UserCostThrottle(redis=None)
        context = make_context()

        result = await throttle.allow_request(context)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_denies_when_over_limit(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import UserCostThrottle

        throttle = UserCostThrottle(redis=None)
        context = make_context()

        await throttle.record_cost(context, 2.0)

        result = await throttle.allow_request(context)
        assert result.allowed is False
        assert result.scope == "user_cost"
        assert result.detail == "User rate limit exceeded"

    @pytest.mark.asyncio
    async def test_different_users_have_separate_limits(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import UserCostThrottle

        throttle = UserCostThrottle(redis=None)

        user1 = make_user(user_id=1)
        user2 = make_user(user_id=2)

        ctx_user1 = make_context(user=user1)
        ctx_user2 = make_context(user=user2)

        await throttle.record_cost(ctx_user1, 2.0)

        result_user1 = await throttle.allow_request(ctx_user1)
        result_user2 = await throttle.allow_request(ctx_user2)

        assert result_user1.allowed is False
        assert result_user2.allowed is True

    @pytest.mark.asyncio
    async def test_cache_key_includes_user_id(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import UserCostThrottle

        throttle = UserCostThrottle(redis=None)
        user = make_user(user_id=42)
        context = make_context(user=user)

        key = throttle._get_cache_key(context)
        assert key == "cost:user:42"


class TestRetryAfterHeader:
    @pytest.mark.asyncio
    async def test_retry_after_returns_full_window_without_redis(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import UserCostThrottle

        throttle = UserCostThrottle(redis=None)
        context = make_context()

        await throttle.record_cost(context, 2.0)
        result = await throttle.allow_request(context)

        assert result.allowed is False
        assert result.retry_after == 3600

    @pytest.mark.asyncio
    async def test_retry_after_returns_ttl_from_redis(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from llm_gateway.rate_limiting.cost_throttles import UserCostThrottle

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=b"10.0")
        mock_redis.ttl = AsyncMock(return_value=600)

        throttle = UserCostThrottle(redis=mock_redis)
        context = make_context()

        result = await throttle.allow_request(context)

        assert result.allowed is False
        assert result.retry_after == 600
        mock_redis.ttl.assert_called_once()


class TestCostAccumulation:
    @pytest.mark.asyncio
    async def test_multiple_small_costs_accumulate_to_limit(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import UserCostThrottle

        throttle = UserCostThrottle(redis=None)
        context = make_context()

        for _ in range(10):
            await throttle.record_cost(context, 0.19)
            result = await throttle.allow_request(context)
            assert result.allowed is True

        await throttle.record_cost(context, 0.19)
        result = await throttle.allow_request(context)
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_zero_cost_not_recorded(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import UserCostThrottle

        throttle = UserCostThrottle(redis=None)
        context = make_context()

        await throttle.record_cost(context, 0.0)
        await throttle.record_cost(context, -1.0)

        limiter = throttle._get_limiter(context)
        key = throttle._get_cache_key(context)
        current = await limiter.get_current(key)
        assert current == 0.0


class TestCostRateLimiterRedisIntegration:
    @pytest.mark.asyncio
    async def test_redis_incr_called_with_correct_args(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from llm_gateway.rate_limiting.cost_throttles import UserCostThrottle

        mock_redis = MagicMock()
        mock_redis.eval = AsyncMock(return_value=0.5)
        mock_redis.get = AsyncMock(return_value=b"0.0")

        throttle = UserCostThrottle(redis=mock_redis)
        context = make_context()

        await throttle.record_cost(context, 0.5)

        mock_redis.eval.assert_called_once()
        call_args = mock_redis.eval.call_args
        assert "ratelimit:cost:user:1" in call_args[0]

    @pytest.mark.asyncio
    async def test_redis_get_current_returns_accumulated_cost(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from llm_gateway.rate_limiting.cost_throttles import UserCostThrottle

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=b"1.5")

        throttle = UserCostThrottle(redis=mock_redis)
        context = make_context()

        limiter = throttle._get_limiter(context)
        current = await limiter.get_current(throttle._get_cache_key(context))

        assert current == 1.5

    @pytest.mark.asyncio
    async def test_redis_ttl_returns_remaining_time(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from llm_gateway.rate_limiting.cost_throttles import UserCostThrottle

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=b"5.0")
        mock_redis.ttl = AsyncMock(return_value=1800)

        throttle = UserCostThrottle(redis=mock_redis)
        context = make_context()

        result = await throttle.allow_request(context)

        assert result.allowed is False
        assert result.retry_after == 1800

    @pytest.mark.asyncio
    async def test_falls_back_to_local_on_redis_error(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from llm_gateway.rate_limiting.cost_throttles import UserCostThrottle

        mock_redis = MagicMock()
        mock_redis.eval = AsyncMock(side_effect=Exception("Redis error"))
        mock_redis.get = AsyncMock(side_effect=Exception("Redis error"))

        throttle = UserCostThrottle(redis=mock_redis)
        context = make_context()

        await throttle.record_cost(context, 0.1)

        result = await throttle.allow_request(context)
        assert result.allowed is True


class TestTeamRateLimitMultipliers:
    @pytest.mark.asyncio
    async def test_cache_key_has_no_suffix_for_default_multiplier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", "{}")
        get_settings.cache_clear()

        from llm_gateway.rate_limiting.cost_throttles import UserCostThrottle

        throttle = UserCostThrottle(redis=None)
        user = make_user(user_id=1, team_id=99)
        context = make_context(user=user)

        key = throttle._get_cache_key(context)
        assert ":tm" not in key
        assert key == "cost:user:1"
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_cache_key_includes_multiplier_suffix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", '{"2": 10}')
        get_settings.cache_clear()

        from llm_gateway.rate_limiting.cost_throttles import UserCostThrottle

        throttle = UserCostThrottle(redis=None)
        user = make_user(user_id=1, team_id=2)
        context = make_context(user=user)

        key = throttle._get_cache_key(context)
        assert key == "cost:user:1:tm10"
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_team_with_multiplier_gets_higher_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", '{"2": 10}')
        get_settings.cache_clear()

        from llm_gateway.rate_limiting.cost_throttles import UserCostThrottle

        throttle = UserCostThrottle(redis=None)
        user = make_user(user_id=1, team_id=2)
        context = make_context(user=user)

        await throttle.record_cost(context, 2.0)
        result = await throttle.allow_request(context)
        assert result.allowed is True, "Should allow - team has 10x multiplier ($20 limit vs $2 used)"

        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_product_cache_key_includes_multiplier_suffix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", '{"2": 10}')
        get_settings.cache_clear()

        from llm_gateway.rate_limiting.cost_throttles import ProductCostThrottle

        throttle = ProductCostThrottle(redis=None)
        user = make_user(user_id=1, team_id=2)
        context = make_context(user=user, product="wizard")

        key = throttle._get_cache_key(context)
        assert key == "cost:product:wizard:tm10"
        get_settings.cache_clear()


class TestCostAccumulatorTTL:
    def test_cost_expires_after_window(self) -> None:
        from unittest.mock import patch

        from llm_gateway.rate_limiting.redis_limiter import CostAccumulator

        accumulator = CostAccumulator(limit=10.0, window_seconds=60)

        with patch("llm_gateway.rate_limiting.redis_limiter.time.monotonic", return_value=0):
            accumulator.incr("user1", 5.0)
            assert accumulator.get_current("user1") == 5.0

        with patch("llm_gateway.rate_limiting.redis_limiter.time.monotonic", return_value=61):
            assert accumulator.get_current("user1") == 0.0

    def test_cost_persists_within_window(self) -> None:
        from unittest.mock import patch

        from llm_gateway.rate_limiting.redis_limiter import CostAccumulator

        accumulator = CostAccumulator(limit=10.0, window_seconds=60)

        with patch("llm_gateway.rate_limiting.redis_limiter.time.monotonic", return_value=0):
            accumulator.incr("user1", 5.0)

        with patch("llm_gateway.rate_limiting.redis_limiter.time.monotonic", return_value=30):
            assert accumulator.get_current("user1") == 5.0
            accumulator.incr("user1", 3.0)
            assert accumulator.get_current("user1") == 8.0

    def test_new_window_starts_fresh(self) -> None:
        from unittest.mock import patch

        from llm_gateway.rate_limiting.redis_limiter import CostAccumulator

        accumulator = CostAccumulator(limit=10.0, window_seconds=60)

        with patch("llm_gateway.rate_limiting.redis_limiter.time.monotonic", return_value=0):
            accumulator.incr("user1", 10.0)
            assert accumulator.incr("user1", 1.0) is False

        with patch("llm_gateway.rate_limiting.redis_limiter.time.monotonic", return_value=61):
            assert accumulator.incr("user1", 5.0) is True
            assert accumulator.get_current("user1") == 5.0

    def test_different_keys_independent(self) -> None:
        from llm_gateway.rate_limiting.redis_limiter import CostAccumulator

        accumulator = CostAccumulator(limit=10.0, window_seconds=60)

        accumulator.incr("user1", 5.0)
        accumulator.incr("user2", 3.0)

        assert accumulator.get_current("user1") == 5.0
        assert accumulator.get_current("user2") == 3.0
