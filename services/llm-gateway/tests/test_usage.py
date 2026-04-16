from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from llm_gateway.api.usage import _to_cost_limit_status
from llm_gateway.config import get_settings
from llm_gateway.rate_limiting.cost_throttles import (
    CostStatus,
    UserCostBurstThrottle,
    UserCostSustainedThrottle,
)
from llm_gateway.services.plan_resolver import PlanInfo
from tests.conftest import create_test_app


class TestToCostLimitStatus:
    @pytest.mark.parametrize(
        "used_usd,limit_usd,expected_percent",
        [
            (0.0, 100.0, 0.0),
            (25.5, 100.0, 25.5),
            (100.0, 100.0, 100.0),
            (150.0, 100.0, 100.0),
            (0.0, 0.0, 100.0),
            (5.0, 0.0, 100.0),
        ],
    )
    def test_used_percent(self, used_usd: float, limit_usd: float, expected_percent: float) -> None:
        status = CostStatus(
            used_usd=used_usd, limit_usd=limit_usd, remaining_usd=0.0, resets_in_seconds=60, exceeded=False
        )
        result = _to_cost_limit_status(status)
        assert result.used_percent == expected_percent

    def test_passes_through_exceeded_and_resets(self) -> None:
        status = CostStatus(used_usd=100.0, limit_usd=100.0, remaining_usd=0.0, resets_in_seconds=3600, exceeded=True)
        result = _to_cost_limit_status(status)
        assert result.exceeded is True
        assert result.resets_in_seconds == 3600


class TestUsageEndpoint:
    @pytest.fixture
    def authenticated_usage_client(self, mock_db_pool: MagicMock) -> TestClient:
        app = create_test_app(mock_db_pool)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": "key_id",
                "user_id": 42,
                "scopes": ["llm_gateway:read"],
                "current_team_id": 1,
                "distinct_id": "test-distinct-id",
            }
        )
        mock_db_pool.acquire = AsyncMock(return_value=conn)
        mock_db_pool.release = AsyncMock()

        with TestClient(app) as c:
            yield c

    def test_returns_pro_limits_when_flag_off(self, authenticated_usage_client: TestClient) -> None:
        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["product"] == "posthog_code"
        assert data["user_id"] == 42
        assert data["burst"]["used_percent"] == 0
        assert data["sustained"]["used_percent"] == 0
        assert data["is_rate_limited"] is False

    def test_returns_trial_limits_when_flag_on(
        self, authenticated_usage_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_GATEWAY_PLAN_AWARE_THROTTLING_ENABLED", "true")
        get_settings.cache_clear()

        app = authenticated_usage_client.app
        app.state.plan_resolver.get_plan = AsyncMock(
            return_value=PlanInfo(plan_key=None, in_trial_period=True, seat_created_at=None)
        )

        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["burst"]["used_percent"] == 0
        assert data["sustained"]["used_percent"] == 0
        get_settings.cache_clear()

    def test_returns_zero_limits_when_trial_expired(
        self, authenticated_usage_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_GATEWAY_PLAN_AWARE_THROTTLING_ENABLED", "true")
        get_settings.cache_clear()

        app = authenticated_usage_client.app
        app.state.plan_resolver.get_plan = AsyncMock(
            return_value=PlanInfo(plan_key="posthog-code-free-20260301", in_trial_period=False, seat_created_at=None)
        )

        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["burst"]["used_percent"] == 100.0
        assert data["burst"]["exceeded"] is True
        assert data["sustained"]["used_percent"] == 100.0
        assert data["sustained"]["exceeded"] is True
        assert data["is_rate_limited"] is True
        get_settings.cache_clear()

    def test_returns_pro_limits_with_pro_plan(
        self, authenticated_usage_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_GATEWAY_PLAN_AWARE_THROTTLING_ENABLED", "true")
        get_settings.cache_clear()

        app = authenticated_usage_client.app
        app.state.plan_resolver.get_plan = AsyncMock(
            return_value=PlanInfo(plan_key="posthog-code-200-20260301", in_trial_period=False, seat_created_at=None)
        )

        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["burst"]["used_percent"] == 0
        assert data["sustained"]["used_percent"] == 0
        assert data["is_rate_limited"] is False
        get_settings.cache_clear()

    def test_returns_401_without_auth(self, client: TestClient) -> None:
        response = client.get("/v1/usage/posthog_code")
        assert response.status_code == 401

    def test_reflects_accumulated_cost(
        self, authenticated_usage_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = authenticated_usage_client.app
        runner = app.state.throttle_runner

        burst_throttle = next(t for t in runner.throttles if isinstance(t, UserCostBurstThrottle))
        sustained_throttle = next(t for t in runner.throttles if isinstance(t, UserCostSustainedThrottle))

        monkeypatch.setattr(
            burst_throttle,
            "get_status",
            AsyncMock(
                return_value=CostStatus(
                    used_usd=25.5, limit_usd=100.0, remaining_usd=74.5, resets_in_seconds=3600, exceeded=False
                )
            ),
        )
        monkeypatch.setattr(
            sustained_throttle,
            "get_status",
            AsyncMock(
                return_value=CostStatus(
                    used_usd=25.5, limit_usd=1000.0, remaining_usd=974.5, resets_in_seconds=86400, exceeded=False
                )
            ),
        )

        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["burst"]["used_percent"] == 25.5
        assert data["burst"]["exceeded"] is False

        assert data["sustained"]["used_percent"] == 2.5
        assert data["sustained"]["exceeded"] is False

    def test_shows_rate_limited_when_burst_exceeded(
        self, authenticated_usage_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = authenticated_usage_client.app
        runner = app.state.throttle_runner

        burst_throttle = next(t for t in runner.throttles if isinstance(t, UserCostBurstThrottle))
        sustained_throttle = next(t for t in runner.throttles if isinstance(t, UserCostSustainedThrottle))

        monkeypatch.setattr(
            burst_throttle,
            "get_status",
            AsyncMock(
                return_value=CostStatus(
                    used_usd=100.0, limit_usd=100.0, remaining_usd=0, resets_in_seconds=3600, exceeded=True
                )
            ),
        )
        monkeypatch.setattr(
            sustained_throttle,
            "get_status",
            AsyncMock(
                return_value=CostStatus(
                    used_usd=100.0, limit_usd=1000.0, remaining_usd=900.0, resets_in_seconds=86400, exceeded=False
                )
            ),
        )

        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["burst"]["exceeded"] is True
        assert data["is_rate_limited"] is True

    def test_ignores_user_id_query_param(self, authenticated_usage_client: TestClient) -> None:
        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code?user_id=99",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        assert response.json()["user_id"] == 42

    def test_invalidate_plan_cache_calls_resolver(self, authenticated_usage_client: TestClient) -> None:
        app = authenticated_usage_client.app
        app.state.plan_resolver.invalidate = AsyncMock()

        response = authenticated_usage_client.post(
            "/v1/usage/posthog_code/invalidate-plan-cache",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        app.state.plan_resolver.invalidate.assert_called_once_with(42)

    def test_invalidate_plan_cache_404_for_other_product(self, authenticated_usage_client: TestClient) -> None:
        response = authenticated_usage_client.post(
            "/v1/usage/wizard/invalidate-plan-cache",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 404

    def test_invalidate_plan_cache_401_without_auth(self, client: TestClient) -> None:
        response = client.post("/v1/usage/posthog_code/invalidate-plan-cache")
        assert response.status_code == 401
