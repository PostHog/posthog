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
