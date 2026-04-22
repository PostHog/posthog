from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_gateway.services.plan_resolver import (
    PlanResolver,
    get_billing_period_number,
    is_pro_plan,
)


class TestIsProPlan:
    @pytest.mark.parametrize(
        "plan_key,expected",
        [
            ("posthog-code-200-20260301", True),
            ("posthog-code-200-20260501", True),
            ("posthog-code-free-20260301", False),
            ("posthog-code-free-20260501", False),
            ("some-other-plan", False),
            (None, False),
            ("", False),
        ],
    )
    def test_is_pro_plan(self, plan_key: str | None, expected: bool) -> None:
        assert is_pro_plan(plan_key) is expected


class TestGetBillingPeriodNumber:
    def test_none_returns_zero(self) -> None:
        assert get_billing_period_number(None) == 0

    def test_invalid_date_returns_zero(self) -> None:
        assert get_billing_period_number("not-a-date") == 0

    def test_today_returns_zero(self) -> None:
        now = datetime.now(tz=UTC).isoformat()
        assert get_billing_period_number(now) == 0

    def test_five_days_ago_returns_zero(self) -> None:
        created = (datetime.now(tz=UTC) - timedelta(days=5)).isoformat()
        assert get_billing_period_number(created) == 0

    def test_thirty_days_returns_one(self) -> None:
        created = (datetime.now(tz=UTC) - timedelta(days=30)).isoformat()
        assert get_billing_period_number(created) == 1

    def test_sixty_days_returns_two(self) -> None:
        created = (datetime.now(tz=UTC) - timedelta(days=60)).isoformat()
        assert get_billing_period_number(created) == 2

    def test_custom_period_days(self) -> None:
        created = (datetime.now(tz=UTC) - timedelta(days=15)).isoformat()
        assert get_billing_period_number(created, period_days=7) == 2

    def test_just_under_boundary(self) -> None:
        created = (datetime.now(tz=UTC) - timedelta(days=29, hours=23)).isoformat()
        assert get_billing_period_number(created) == 0


class TestPlanResolver:
    @pytest.fixture
    def resolver(self) -> PlanResolver:
        return PlanResolver(redis=None, http_client=AsyncMock())

    @pytest.fixture
    def resolver_with_redis(self) -> PlanResolver:
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        return PlanResolver(redis=redis, http_client=AsyncMock())

    async def test_returns_none_plan_when_no_api_url(self, resolver: PlanResolver) -> None:
        with patch("llm_gateway.services.plan_resolver.get_settings") as mock_settings:
            mock_settings.return_value.posthog_api_base_url = ""
            mock_settings.return_value.plan_cache_ttl = 300
            result = await resolver.get_plan(user_id=1, auth_header="Bearer phx_test")
        assert result.plan_key is None

    async def test_returns_cached_plan(self, resolver_with_redis: PlanResolver) -> None:
        import json

        cached = json.dumps({"plan_key": "posthog-code-200-20260301", "created_at": None})
        assert resolver_with_redis._redis is not None
        resolver_with_redis._redis.get = AsyncMock(return_value=cached.encode())  # type: ignore[method-assign]
        result = await resolver_with_redis.get_plan(user_id=1, auth_header="Bearer phx_test")
        assert result.plan_key == "posthog-code-200-20260301"

    async def test_cached_null_plan_returns_none_plan_key(self, resolver_with_redis: PlanResolver) -> None:
        import json

        cached = json.dumps({"plan_key": None, "created_at": None})
        assert resolver_with_redis._redis is not None
        resolver_with_redis._redis.get = AsyncMock(return_value=cached.encode())  # type: ignore[method-assign]
        result = await resolver_with_redis.get_plan(user_id=1, auth_header="Bearer phx_test")
        assert result.plan_key is None

    async def test_cached_old_seat_returns_plan(self, resolver_with_redis: PlanResolver) -> None:
        import json

        old_date = (datetime.now(tz=UTC) - timedelta(days=60)).isoformat()
        cached = json.dumps({"plan_key": "posthog-code-free-20260301", "created_at": old_date})
        assert resolver_with_redis._redis is not None
        resolver_with_redis._redis.get = AsyncMock(return_value=cached.encode())  # type: ignore[method-assign]
        result = await resolver_with_redis.get_plan(user_id=1, auth_header="Bearer phx_test")
        assert result.plan_key == "posthog-code-free-20260301"
        assert result.seat_created_at == old_date

    async def test_fetches_from_api_and_caches(self, resolver_with_redis: PlanResolver) -> None:
        created_at = datetime.now(tz=UTC).isoformat()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"plan_key": "posthog-code-200-20260301", "created_at": created_at}
        mock_resp.raise_for_status = MagicMock()
        resolver_with_redis._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]

        with patch("llm_gateway.services.plan_resolver.get_settings") as mock_settings:
            mock_settings.return_value.posthog_api_base_url = "https://app.posthog.com"
            mock_settings.return_value.plan_cache_ttl = 300
            result = await resolver_with_redis.get_plan(user_id=1, auth_header="Bearer phx_test")

        assert result.plan_key == "posthog-code-200-20260301"
        assert resolver_with_redis._redis is not None
        resolver_with_redis._redis.set.assert_called_once()  # type: ignore[attr-defined]

        resolver_with_redis._http.get.assert_called_once_with(
            "https://app.posthog.com/api/seats/me/",
            params={"product_key": "posthog_code"},
            headers={"Authorization": "Bearer phx_test"},
            timeout=2.0,
        )

    async def test_forwards_auth_header(self, resolver: PlanResolver) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"plan_key": None, "created_at": None}
        mock_resp.raise_for_status = MagicMock()
        resolver._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]

        with patch("llm_gateway.services.plan_resolver.get_settings") as mock_settings:
            mock_settings.return_value.posthog_api_base_url = "https://app.posthog.com"
            mock_settings.return_value.plan_cache_ttl = 300
            await resolver.get_plan(user_id=1, auth_header="Bearer phx_mysecretkey")

        resolver._http.get.assert_called_once()
        call_kwargs = resolver._http.get.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer phx_mysecretkey"

    async def test_404_returns_none_plan(self, resolver: PlanResolver) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        resolver._http.get = AsyncMock(return_value=mock_resp)  # type: ignore[method-assign]

        with patch("llm_gateway.services.plan_resolver.get_settings") as mock_settings:
            mock_settings.return_value.posthog_api_base_url = "https://app.posthog.com"
            mock_settings.return_value.plan_cache_ttl = 300
            result = await resolver.get_plan(user_id=1, auth_header="Bearer phx_test")

        assert result.plan_key is None

    async def test_api_error_returns_none_plan(self, resolver: PlanResolver) -> None:
        resolver._http.get = AsyncMock(side_effect=Exception("connection refused"))  # type: ignore[method-assign]

        with patch("llm_gateway.services.plan_resolver.get_settings") as mock_settings:
            mock_settings.return_value.posthog_api_base_url = "https://app.posthog.com"
            mock_settings.return_value.plan_cache_ttl = 300
            result = await resolver.get_plan(user_id=1, auth_header="Bearer phx_test")

        assert result.plan_key is None

    async def test_empty_auth_header_skips_fetch(self, resolver: PlanResolver) -> None:
        result = await resolver.get_plan(user_id=1, auth_header="")
        assert result.plan_key is None
        resolver._http.get.assert_not_called()  # type: ignore[attr-defined]

    async def test_api_error_not_cached(self, resolver_with_redis: PlanResolver) -> None:
        resolver_with_redis._http.get = AsyncMock(side_effect=Exception("connection refused"))  # type: ignore[method-assign]

        with patch("llm_gateway.services.plan_resolver.get_settings") as mock_settings:
            mock_settings.return_value.posthog_api_base_url = "https://app.posthog.com"
            mock_settings.return_value.plan_cache_ttl = 300
            result = await resolver_with_redis.get_plan(user_id=1, auth_header="Bearer phx_test")

        assert result.plan_key is None
        assert resolver_with_redis._redis is not None
        resolver_with_redis._redis.set.assert_not_called()  # type: ignore[attr-defined]
