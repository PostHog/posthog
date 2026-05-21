from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.rate_limiting.billable_credits_throttle import (
    _AI_CREDITS_LIMIT_KEY,
    BillableCreditThrottle,
)
from llm_gateway.rate_limiting.throttles import ThrottleContext

_TEAM_TOKEN = "phc_team_under_test"


def _make_user(team_api_token: str | None = _TEAM_TOKEN) -> AuthenticatedUser:
    return AuthenticatedUser(
        user_id=1,
        team_id=42,
        auth_method="personal_api_key",
        distinct_id="distinct-1",
        scopes=["llm_gateway:read"],
        team_api_token=team_api_token,
    )


def _make_context(product: str, user: AuthenticatedUser | None = None) -> ThrottleContext:
    return ThrottleContext(user=user or _make_user(), product=product)


class TestBillableCreditThrottle:
    @pytest.mark.asyncio
    async def test_allows_non_billable_product_without_redis_lookup(self) -> None:
        redis = AsyncMock()
        throttle = BillableCreditThrottle(redis=redis, clock=lambda: 1_000_000)

        result = await throttle.allow_request(_make_context(product="posthog_code"))

        assert result.allowed is True
        redis.zscore.assert_not_called()

    @pytest.mark.asyncio
    async def test_allows_billable_product_when_team_not_limited(self) -> None:
        redis = AsyncMock()
        redis.zscore = AsyncMock(return_value=None)
        throttle = BillableCreditThrottle(redis=redis, clock=lambda: 1_000_000)

        result = await throttle.allow_request(_make_context(product="slack_app"))

        assert result.allowed is True
        redis.zscore.assert_awaited_once_with(_AI_CREDITS_LIMIT_KEY, _TEAM_TOKEN)

    @pytest.mark.asyncio
    async def test_allows_billable_product_when_limit_expired(self) -> None:
        redis = AsyncMock()
        redis.zscore = AsyncMock(return_value=999_999.0)
        throttle = BillableCreditThrottle(redis=redis, clock=lambda: 1_000_000)

        result = await throttle.allow_request(_make_context(product="slack_app"))

        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_denies_billable_product_when_team_currently_limited(self) -> None:
        redis = AsyncMock()
        redis.zscore = AsyncMock(return_value=1_003_600.0)
        throttle = BillableCreditThrottle(redis=redis, clock=lambda: 1_000_000)

        result = await throttle.allow_request(_make_context(product="slack_app"))

        assert result.allowed is False
        assert result.status_code == 429
        assert result.scope == "billable_credits"
        assert "PostHog AI credits" in result.detail
        assert result.retry_after == 3600

    @pytest.mark.asyncio
    async def test_allows_when_redis_is_not_configured(self) -> None:
        throttle = BillableCreditThrottle(redis=None, clock=lambda: 1_000_000)

        result = await throttle.allow_request(_make_context(product="slack_app"))

        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_allows_when_team_api_token_is_missing(self) -> None:
        redis = AsyncMock()
        throttle = BillableCreditThrottle(redis=redis, clock=lambda: 1_000_000)
        user_without_token = _make_user(team_api_token=None)

        result = await throttle.allow_request(_make_context(product="slack_app", user=user_without_token))

        assert result.allowed is True
        redis.zscore.assert_not_called()
