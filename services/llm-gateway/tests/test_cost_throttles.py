import pytest

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.config import get_settings
from llm_gateway.rate_limiting.throttles import ThrottleContext


def make_user(user_id: int = 1, team_id: int = 1, auth_method: str = "oauth_access_token") -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=user_id,
        team_id=team_id,
        auth_method=auth_method,
        distinct_id=f"test-distinct-id-{user_id}",
        scopes=["llm_gateway:read"],
    )


def make_context(
    user: AuthenticatedUser | None = None,
    product: str = "twig",
    end_user_id: str | None = None,
) -> ThrottleContext:
    user = user or make_user()
    if end_user_id is None and user.auth_method == "oauth_access_token":
        end_user_id = str(user.user_id)
    return ThrottleContext(
        user=user,
        product=product,
        end_user_id=end_user_id,
    )


class TestProductCostLimitConfig:
    def test_default_product_cost_limits(self) -> None:
        get_settings.cache_clear()
        settings = get_settings()
        assert "llm_gateway" in settings.product_cost_limits
        assert settings.product_cost_limits["llm_gateway"].limit_usd == 1000.0
        assert settings.product_cost_limits["llm_gateway"].window_seconds == 86400

    def test_parses_json_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "LLM_GATEWAY_PRODUCT_COST_LIMITS",
            '{"wizard": {"limit_usd": 100, "window_seconds": 86400}, "twig": {"limit_usd": 50, "window_seconds": 14400}}',
        )
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.product_cost_limits["wizard"].limit_usd == 100.0
        assert settings.product_cost_limits["wizard"].window_seconds == 86400
        assert settings.product_cost_limits["twig"].limit_usd == 50.0
        assert settings.product_cost_limits["twig"].window_seconds == 14400
        get_settings.cache_clear()


class TestUserCostLimitConfig:
    def test_default_user_cost_limits(self) -> None:
        get_settings.cache_clear()
        settings = get_settings()
        assert "twig" in settings.user_cost_limits
        twig = settings.user_cost_limits["twig"]
        assert twig.burst_limit_usd == 100.0
        assert twig.burst_window_seconds == 86400
        assert twig.sustained_limit_usd == 1000.0
        assert twig.sustained_window_seconds == 2592000
        get_settings.cache_clear()

    def test_parses_json_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "LLM_GATEWAY_USER_COST_LIMITS",
            '{"twig": {"burst_limit_usd": 50, "burst_window_seconds": 86400, "sustained_limit_usd": 500, "sustained_window_seconds": 2592000}}',
        )
        get_settings.cache_clear()
        settings = get_settings()
        twig = settings.user_cost_limits["twig"]
        assert twig.burst_limit_usd == 50.0
        assert twig.sustained_limit_usd == 500.0
        get_settings.cache_clear()

    def test_unset_env_returns_defaults(self) -> None:
        get_settings.cache_clear()
        settings = get_settings()
        assert "twig" in settings.user_cost_limits
        get_settings.cache_clear()


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

        await throttle.record_cost(context, 1000.0)

        result = await throttle.allow_request(context)
        assert result.allowed is False
        assert result.scope == "product_cost"
        assert result.detail == "Product rate limit exceeded"

    @pytest.mark.asyncio
    async def test_different_products_have_separate_limits(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import ProductCostThrottle

        throttle = ProductCostThrottle(redis=None)

        ctx_wizard = make_context(product="wizard")
        ctx_twig = make_context(product="twig")

        await throttle.record_cost(ctx_wizard, 2000.0)

        result_wizard = await throttle.allow_request(ctx_wizard)
        result_twig = await throttle.allow_request(ctx_twig)

        assert result_wizard.allowed is False
        assert result_twig.allowed is True

    @pytest.mark.asyncio
    async def test_cache_key_format(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import ProductCostThrottle

        throttle = ProductCostThrottle(redis=None)
        context = make_context(product="wizard")

        key = throttle._get_cache_key(context)
        assert key == "cost:product:wizard"


class TestUserCostBurstThrottle:
    @pytest.mark.asyncio
    async def test_allows_when_under_limit(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="twig")

        result = await throttle.allow_request(context)
        assert result.allowed is True
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_denies_when_over_burst_limit(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="twig")

        await throttle.record_cost(context, 100.0)

        result = await throttle.allow_request(context)
        assert result.allowed is False
        assert result.scope == "user_cost_burst"
        assert result.detail == "User burst rate limit exceeded"
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_uses_default_for_products_without_config(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="llm_gateway")

        await throttle.record_cost(context, 99.0)
        result = await throttle.allow_request(context)
        assert result.allowed is True

        await throttle.record_cost(context, 1.0)
        result = await throttle.allow_request(context)
        assert result.allowed is False
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_skips_without_end_user_id(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        user = make_user(user_id=1, auth_method="personal_api_key")
        context = make_context(user=user, product="twig", end_user_id=None)

        await throttle.record_cost(context, 99999.0)
        result = await throttle.allow_request(context)
        assert result.allowed is True
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_cache_key_includes_product_and_scope(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="twig", end_user_id="42")

        key = throttle._get_cache_key(context)
        assert key == "cost:user:user_cost_burst:twig:42"

    @pytest.mark.asyncio
    async def test_different_users_have_separate_limits(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)

        user1 = make_user(user_id=1)
        user2 = make_user(user_id=2)
        ctx1 = make_context(user=user1, product="twig")
        ctx2 = make_context(user=user2, product="twig")

        await throttle.record_cost(ctx1, 100.0)

        assert (await throttle.allow_request(ctx1)).allowed is False
        assert (await throttle.allow_request(ctx2)).allowed is True
        get_settings.cache_clear()


class TestUserCostSustainedThrottle:
    @pytest.mark.asyncio
    async def test_allows_when_under_limit(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostSustainedThrottle

        throttle = UserCostSustainedThrottle(redis=None)
        context = make_context(product="twig")

        result = await throttle.allow_request(context)
        assert result.allowed is True
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_denies_when_over_sustained_limit(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostSustainedThrottle

        throttle = UserCostSustainedThrottle(redis=None)
        context = make_context(product="twig")

        await throttle.record_cost(context, 1000.0)

        result = await throttle.allow_request(context)
        assert result.allowed is False
        assert result.scope == "user_cost_sustained"
        assert result.detail == "User sustained rate limit exceeded"
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_uses_default_for_products_without_config(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostSustainedThrottle

        throttle = UserCostSustainedThrottle(redis=None)
        context = make_context(product="llm_gateway")

        await throttle.record_cost(context, 999.0)
        result = await throttle.allow_request(context)
        assert result.allowed is True

        await throttle.record_cost(context, 1.0)
        result = await throttle.allow_request(context)
        assert result.allowed is False
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_cache_key_includes_product_and_scope(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import UserCostSustainedThrottle

        throttle = UserCostSustainedThrottle(redis=None)
        context = make_context(product="twig", end_user_id="42")

        key = throttle._get_cache_key(context)
        assert key == "cost:user:user_cost_sustained:twig:42"


class TestBurstSustainedInteraction:
    @pytest.mark.asyncio
    async def test_burst_denies_before_sustained(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle, UserCostSustainedThrottle

        burst = UserCostBurstThrottle(redis=None)
        sustained = UserCostSustainedThrottle(redis=None)
        context = make_context(product="twig")

        await burst.record_cost(context, 100.0)
        await sustained.record_cost(context, 100.0)

        assert (await burst.allow_request(context)).allowed is False
        assert (await sustained.allow_request(context)).allowed is True
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_sustained_denies_even_if_burst_allows(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle, UserCostSustainedThrottle

        burst = UserCostBurstThrottle(redis=None)
        sustained = UserCostSustainedThrottle(redis=None)
        context = make_context(product="twig")

        await burst.record_cost(context, 50.0)
        await sustained.record_cost(context, 1000.0)

        assert (await burst.allow_request(context)).allowed is True
        assert (await sustained.allow_request(context)).allowed is False
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_custom_limits_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "LLM_GATEWAY_USER_COST_LIMITS",
            '{"twig": {"burst_limit_usd": 200, "burst_window_seconds": 86400, "sustained_limit_usd": 2000, "sustained_window_seconds": 2592000}}',
        )
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="twig")

        await throttle.record_cost(context, 150.0)
        assert (await throttle.allow_request(context)).allowed is True

        await throttle.record_cost(context, 60.0)
        assert (await throttle.allow_request(context)).allowed is False
        get_settings.cache_clear()


class TestUserCostDisabledFlag:
    @pytest.mark.asyncio
    async def test_allows_when_limits_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_USER_COST_LIMITS_DISABLED", "true")
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="twig")

        await throttle.record_cost(context, 1000.0)
        result = await throttle.allow_request(context)
        assert result.allowed is True
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_tracks_but_does_not_enforce_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("LLM_GATEWAY_USER_COST_LIMITS_DISABLED", "true")
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="twig")

        await throttle.record_cost(context, 1000.0)
        result = await throttle.allow_request(context)

        captured = capsys.readouterr()
        assert result.allowed is True
        assert "cost_throttle_exceeded" in captured.out
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_enforces_when_limits_enabled(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="twig")

        await throttle.record_cost(context, 1000.0)
        result = await throttle.allow_request(context)
        assert result.allowed is False
        assert result.scope == "user_cost_burst"
        get_settings.cache_clear()


class TestRetryAfterHeader:
    @pytest.mark.asyncio
    async def test_retry_after_returns_full_window_without_redis(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="twig")

        await throttle.record_cost(context, 100.0)
        result = await throttle.allow_request(context)

        assert result.allowed is False
        assert result.retry_after == 86400
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_retry_after_returns_ttl_from_redis(self) -> None:
        get_settings.cache_clear()

        from unittest.mock import AsyncMock, MagicMock

        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=b"1000.0")
        mock_redis.ttl = AsyncMock(return_value=600)

        throttle = UserCostBurstThrottle(redis=mock_redis)
        context = make_context(product="twig")

        result = await throttle.allow_request(context)

        assert result.allowed is False
        assert result.retry_after == 600
        get_settings.cache_clear()


class TestCostAccumulation:
    @pytest.mark.asyncio
    async def test_multiple_small_costs_accumulate_to_limit(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="twig")

        for _ in range(9):
            await throttle.record_cost(context, 10.0)
            result = await throttle.allow_request(context)
            assert result.allowed is True

        await throttle.record_cost(context, 20.0)
        result = await throttle.allow_request(context)
        assert result.allowed is False
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_zero_cost_not_recorded(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="twig")

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

        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        mock_redis = MagicMock()
        mock_redis.eval = AsyncMock(return_value=0.5)
        mock_redis.get = AsyncMock(return_value=b"0.0")

        throttle = UserCostBurstThrottle(redis=mock_redis)
        context = make_context(product="twig")

        await throttle.record_cost(context, 0.5)

        mock_redis.eval.assert_called_once()
        call_args = mock_redis.eval.call_args
        assert "ratelimit:cost:user:user_cost_burst:twig:1" in call_args[0]

    @pytest.mark.asyncio
    async def test_redis_get_current_returns_accumulated_cost(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=b"1.5")

        throttle = UserCostBurstThrottle(redis=mock_redis)
        context = make_context(product="twig")

        limiter = throttle._get_limiter(context)
        current = await limiter.get_current(throttle._get_cache_key(context))

        assert current == 1.5

    @pytest.mark.asyncio
    async def test_redis_ttl_returns_remaining_time(self) -> None:
        get_settings.cache_clear()

        from unittest.mock import AsyncMock, MagicMock

        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(return_value=b"1000.0")
        mock_redis.ttl = AsyncMock(return_value=1800)

        throttle = UserCostBurstThrottle(redis=mock_redis)
        context = make_context(product="twig")

        result = await throttle.allow_request(context)

        assert result.allowed is False
        assert result.retry_after == 1800
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_falls_back_to_local_on_redis_error(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        mock_redis = MagicMock()
        mock_redis.eval = AsyncMock(side_effect=Exception("Redis error"))
        mock_redis.get = AsyncMock(side_effect=Exception("Redis error"))

        throttle = UserCostBurstThrottle(redis=mock_redis)
        context = make_context(product="twig")

        await throttle.record_cost(context, 0.1)

        result = await throttle.allow_request(context)
        assert result.allowed is True


class TestTeamRateLimitMultipliers:
    @pytest.mark.asyncio
    async def test_cache_key_has_no_suffix_for_default_multiplier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", "{}")
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        user = make_user(user_id=1, team_id=99)
        context = make_context(user=user, product="twig")

        key = throttle._get_cache_key(context)
        assert ":tm" not in key
        assert key == "cost:user:user_cost_burst:twig:1"
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_cache_key_includes_multiplier_suffix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", '{"2": 10}')
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        user = make_user(user_id=1, team_id=2)
        context = make_context(user=user, product="twig")

        key = throttle._get_cache_key(context)
        assert key == "cost:user:user_cost_burst:twig:1:tm10"
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_team_with_multiplier_gets_higher_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_TEAM_RATE_LIMIT_MULTIPLIERS", '{"2": 10}')
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        user = make_user(user_id=1, team_id=2)
        context = make_context(user=user, product="twig")

        await throttle.record_cost(context, 100.0)
        result = await throttle.allow_request(context)
        assert result.allowed is True, "Should allow - team has 10x multiplier ($1000 limit vs $100 used)"
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


class TestUnconfiguredProductsUseDefaults:
    """Products without user_cost_limits config use default limits ($100/24h burst, $1000/30d sustained)."""

    @pytest.mark.asyncio
    async def test_unconfigured_product_uses_burst_default(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="wizard")

        await throttle.record_cost(context, 99.0)
        result = await throttle.allow_request(context)
        assert result.allowed is True

        await throttle.record_cost(context, 1.0)
        result = await throttle.allow_request(context)
        assert result.allowed is False
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_unconfigured_product_uses_sustained_default(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostSustainedThrottle

        throttle = UserCostSustainedThrottle(redis=None)
        context = make_context(product="wizard")

        await throttle.record_cost(context, 999.0)
        result = await throttle.allow_request(context)
        assert result.allowed is True

        await throttle.record_cost(context, 1.0)
        result = await throttle.allow_request(context)
        assert result.allowed is False
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_configured_and_unconfigured_products_both_limited(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle, UserCostSustainedThrottle

        burst = UserCostBurstThrottle(redis=None)
        sustained = UserCostSustainedThrottle(redis=None)

        ctx_twig = make_context(product="twig")
        ctx_wizard = make_context(product="wizard")

        await burst.record_cost(ctx_twig, 100.0)
        await burst.record_cost(ctx_wizard, 100.0)
        await sustained.record_cost(ctx_twig, 1000.0)
        await sustained.record_cost(ctx_wizard, 1000.0)

        assert (await burst.allow_request(ctx_twig)).allowed is False
        assert (await burst.allow_request(ctx_wizard)).allowed is False
        assert (await sustained.allow_request(ctx_twig)).allowed is False
        assert (await sustained.allow_request(ctx_wizard)).allowed is False
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_logs_info_for_unconfigured_product_with_end_user(self, capsys: pytest.CaptureFixture[str]) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle, _UserCostThrottleBase

        _UserCostThrottleBase._warned_products = set()

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="wizard")

        await throttle.allow_request(context)
        captured = capsys.readouterr()
        assert "user_cost_limits_using_default" in captured.out
        assert "wizard" in captured.out

        await throttle.allow_request(context)
        captured2 = capsys.readouterr()
        assert "user_cost_limits_using_default" not in captured2.out

        _UserCostThrottleBase._warned_products = set()
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_no_warning_for_unconfigured_product_without_end_user(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle, _UserCostThrottleBase

        _UserCostThrottleBase._warned_products = set()

        throttle = UserCostBurstThrottle(redis=None)
        user = make_user(auth_method="personal_api_key")
        context = make_context(user=user, product="wizard", end_user_id=None)

        await throttle.allow_request(context)
        captured = capsys.readouterr()
        assert "user_cost_limits_using_default" not in captured.out

        _UserCostThrottleBase._warned_products = set()
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_dynamically_adding_product_config_overrides_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="wizard")

        await throttle.record_cost(context, 99.0)
        assert (await throttle.allow_request(context)).allowed is True

        monkeypatch.setenv(
            "LLM_GATEWAY_USER_COST_LIMITS",
            '{"twig": {"burst_limit_usd": 100, "burst_window_seconds": 86400, "sustained_limit_usd": 1000, "sustained_window_seconds": 2592000}, '
            '"wizard": {"burst_limit_usd": 50, "burst_window_seconds": 3600, "sustained_limit_usd": 200, "sustained_window_seconds": 86400}}',
        )
        get_settings.cache_clear()

        await throttle.record_cost(context, 50.0)
        assert (await throttle.allow_request(context)).allowed is False
        get_settings.cache_clear()


class TestUserCostEdgeCases:
    @pytest.mark.asyncio
    async def test_sustained_skips_without_end_user_id(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostSustainedThrottle

        throttle = UserCostSustainedThrottle(redis=None)
        user = make_user(user_id=1, auth_method="personal_api_key")
        context = make_context(user=user, product="twig", end_user_id=None)

        await throttle.record_cost(context, 99999.0)
        result = await throttle.allow_request(context)
        assert result.allowed is True
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_empty_string_end_user_id_treated_as_no_user(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        user = make_user(user_id=1, auth_method="personal_api_key")
        context = make_context(user=user, product="twig", end_user_id="")

        await throttle.record_cost(context, 99999.0)
        result = await throttle.allow_request(context)
        assert result.allowed is True
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_personal_api_key_with_end_user_id_enforces_limits(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        user = make_user(user_id=1, auth_method="personal_api_key")
        context = make_context(user=user, product="twig", end_user_id="ext-user-42")

        await throttle.record_cost(context, 100.0)
        result = await throttle.allow_request(context)
        assert result.allowed is False
        assert result.scope == "user_cost_burst"
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_get_config_returns_default_for_unconfigured_product(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="wizard")

        config = throttle._get_config(context)
        assert config.burst_limit_usd == 100.0
        assert config.burst_window_seconds == 86400
        assert config.sustained_limit_usd == 1000.0
        assert config.sustained_window_seconds == 2592000
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_cache_key_empty_without_end_user_id(self) -> None:
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        user = make_user(auth_method="personal_api_key")
        context = make_context(user=user, product="twig", end_user_id=None)

        assert throttle._get_cache_key(context) == ""

    @pytest.mark.asyncio
    async def test_different_products_same_user_isolated(self) -> None:
        get_settings.cache_clear()
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv(
            "LLM_GATEWAY_USER_COST_LIMITS",
            '{"twig": {"burst_limit_usd": 100, "burst_window_seconds": 86400, "sustained_limit_usd": 1000, "sustained_window_seconds": 2592000}, '
            '"wizard": {"burst_limit_usd": 50, "burst_window_seconds": 3600, "sustained_limit_usd": 200, "sustained_window_seconds": 86400}}',
        )
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)

        ctx_twig = make_context(product="twig", end_user_id="42")
        ctx_wizard = make_context(product="wizard", end_user_id="42")

        await throttle.record_cost(ctx_wizard, 50.0)

        assert (await throttle.allow_request(ctx_wizard)).allowed is False
        assert (await throttle.allow_request(ctx_twig)).allowed is True
        monkeypatch.undo()
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_cost_just_below_limit_still_allowed(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="twig")

        await throttle.record_cost(context, 99.99)
        result = await throttle.allow_request(context)
        assert result.allowed is True
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_cost_exactly_at_limit_denied(self) -> None:
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle

        throttle = UserCostBurstThrottle(redis=None)
        context = make_context(product="twig")

        await throttle.record_cost(context, 100.0)
        result = await throttle.allow_request(context)
        assert result.allowed is False
        get_settings.cache_clear()


class TestUserCostDisabledSustained:
    @pytest.mark.asyncio
    async def test_sustained_allows_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_USER_COST_LIMITS_DISABLED", "true")
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostSustainedThrottle

        throttle = UserCostSustainedThrottle(redis=None)
        context = make_context(product="twig")

        await throttle.record_cost(context, 9999.0)
        result = await throttle.allow_request(context)
        assert result.allowed is True
        get_settings.cache_clear()

    @pytest.mark.asyncio
    async def test_both_burst_and_sustained_allow_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_GATEWAY_USER_COST_LIMITS_DISABLED", "true")
        get_settings.cache_clear()
        from llm_gateway.rate_limiting.cost_throttles import UserCostBurstThrottle, UserCostSustainedThrottle

        burst = UserCostBurstThrottle(redis=None)
        sustained = UserCostSustainedThrottle(redis=None)
        context = make_context(product="twig")

        await burst.record_cost(context, 9999.0)
        await sustained.record_cost(context, 9999.0)

        assert (await burst.allow_request(context)).allowed is True
        assert (await sustained.allow_request(context)).allowed is True
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
