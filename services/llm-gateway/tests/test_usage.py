from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from fastapi.testclient import TestClient

from llm_gateway.api.usage import _to_cost_limit_status
from llm_gateway.rate_limiting.cost_throttles import (
    CostStatus,
    UserCostBurstThrottle,
    UserCostSustainedThrottle,
)
from llm_gateway.services.billing_period_resolver import OrganizationBillingPeriod
from llm_gateway.services.quota_resolver import QuotaResourceStatus
from tests.conftest import create_test_app


class TestToCostLimitStatus:
    NOW = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)

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
        result = _to_cost_limit_status(status, now=self.NOW)
        assert result.used_percent == expected_percent

    def test_passes_through_exceeded_and_resets(self) -> None:
        status = CostStatus(used_usd=100.0, limit_usd=100.0, remaining_usd=0.0, resets_in_seconds=3600, exceeded=True)
        result = _to_cost_limit_status(status, now=self.NOW)
        assert result.exceeded is True
        assert result.resets_in_seconds == 3600

    @pytest.mark.parametrize("resets_in_seconds", [0, 60, 3600, 86400])
    def test_reset_at_matches_resets_in_seconds(self, resets_in_seconds: int) -> None:
        status = CostStatus(
            used_usd=10.0,
            limit_usd=100.0,
            remaining_usd=90.0,
            resets_in_seconds=resets_in_seconds,
            exceeded=False,
        )
        result = _to_cost_limit_status(status, now=self.NOW)
        assert result.reset_at == self.NOW + timedelta(seconds=resets_in_seconds)


class TestUsageEndpoint:
    @pytest.fixture
    def authenticated_usage_client(self, mock_db_pool: MagicMock) -> Generator[TestClient]:
        app = create_test_app(mock_db_pool)

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "id": "key_id",
                "user_id": 42,
                "scopes": ["llm_gateway:read"],
                "current_team_id": 1,
                "distinct_id": "test-distinct-id",
                "is_staff": False,
            }
        )
        mock_db_pool.acquire = AsyncMock(return_value=conn)
        mock_db_pool.release = AsyncMock()

        with TestClient(app) as c:
            yield c

    def test_returns_pro_limits_by_default(self, authenticated_usage_client: TestClient) -> None:
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
        assert "is_pro" in data
        assert "reset_at" in data["burst"]
        assert "reset_at" in data["sustained"]
        assert "billing_period_end" in data

    def test_response_has_no_usd_fields(self, authenticated_usage_client: TestClient) -> None:
        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        data = response.json()
        for bucket in (data["burst"], data["sustained"]):
            for key in bucket:
                assert "usd" not in key.lower(), f"Bucket field {key!r} leaks USD"

    def test_includes_billing_period_end_from_org_period(self, authenticated_usage_client: TestClient) -> None:
        app = authenticated_usage_client.app
        app.state.billing_period_resolver.get_period = AsyncMock(
            return_value=OrganizationBillingPeriod(
                current_period_start="2026-05-01T00:00:00+00:00",
                current_period_end="2026-05-31T00:00:00+00:00",
            )
        )

        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["billing_period_end"] is not None
        assert data["billing_period_end"].startswith("2026-05-31")

    def test_org_usage_billing_period_reported(self, authenticated_usage_client: TestClient) -> None:
        app = authenticated_usage_client.app
        app.state.billing_period_resolver.get_period = AsyncMock(
            return_value=OrganizationBillingPeriod(
                current_period_start="2026-07-09T00:00:00Z",
                current_period_end="2026-08-09T00:00:00Z",
            )
        )
        app.state.quota_resolver.get_resource_status = AsyncMock(
            return_value=QuotaResourceStatus(
                limited=False,
                code_usage_billing_active=True,
                used_usd=12.4,
                limit_usd=50.0,
            )
        )

        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )

        assert response.status_code == 200
        assert response.json()["billing_period_end"].startswith("2026-08-09")

    def test_billing_period_end_normalises_naive_iso_to_utc(self, authenticated_usage_client: TestClient) -> None:
        app = authenticated_usage_client.app
        app.state.billing_period_resolver.get_period = AsyncMock(
            return_value=OrganizationBillingPeriod(
                current_period_start="2026-05-01T00:00:00",
                current_period_end="2026-05-31T00:00:00",
            )
        )

        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        billing_period_end = response.json()["billing_period_end"]
        assert billing_period_end is not None
        parsed = datetime.fromisoformat(billing_period_end)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)

    def test_billing_period_end_null_when_unparseable(self, authenticated_usage_client: TestClient) -> None:
        app = authenticated_usage_client.app
        app.state.billing_period_resolver.get_period = AsyncMock(
            return_value=OrganizationBillingPeriod(
                current_period_start="2026-05-01T00:00:00+00:00",
                current_period_end="not-a-real-date",
            )
        )

        with structlog.testing.capture_logs() as logs:
            response = authenticated_usage_client.get(
                "/v1/usage/posthog_code",
                headers={"Authorization": "Bearer phx_test"},
            )
        assert response.status_code == 200
        assert response.json()["billing_period_end"] is None
        assert any(log.get("event") == "usage.billing_period_end_unparseable" for log in logs)

    def test_billing_period_end_null_without_org_period(self, authenticated_usage_client: TestClient) -> None:
        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        assert response.json()["billing_period_end"] is None

    def test_is_pro_always_false(self, authenticated_usage_client: TestClient) -> None:
        # Seat billing was retired on 2026-07-16, so no caller is on a Pro seat.
        # The field stays in the response until older Desktop builds age out.
        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        assert response.json()["is_pro"] is False

    def test_returns_limits_for_every_caller(self, authenticated_usage_client: TestClient) -> None:
        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["burst"]["used_percent"] == 0
        assert data["burst"]["exceeded"] is False
        assert data["sustained"]["used_percent"] == 0
        assert data["sustained"]["exceeded"] is False
        assert data["is_rate_limited"] is False

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

    def test_credits_reflect_products_own_bucket(self, authenticated_usage_client: TestClient) -> None:
        # posthog_code's usage reports the posthog_code_credits bucket (under the
        # legacy `ai_credits` response field), resolved against its own resource key.
        from llm_gateway.services.quota_resolver import QuotaResourceStatus

        app = authenticated_usage_client.app
        resolver_mock = AsyncMock(return_value=QuotaResourceStatus(limited=True))
        app.state.quota_resolver.get_resource_status = resolver_mock

        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ai_credits"] == {"exhausted": True, "used_usd": None, "limit_usd": None, "breakdown": None}
        assert data["is_rate_limited"] is True
        assert resolver_mock.call_args.args[0] == "posthog_code_credits"

    def test_exhausted_bucket_reported_for_every_caller(self, authenticated_usage_client: TestClient) -> None:
        # Mirrors BillableCreditThrottle: every posthog_code generation counts into
        # the org's bucket, so exhaustion blocks (and must be reported to) every
        # caller — clients gate on this response, and a carve-out here would let
        # them keep sending requests enforcement denies.
        from llm_gateway.services.quota_resolver import QuotaResourceStatus

        app = authenticated_usage_client.app
        app.state.quota_resolver.get_resource_status = AsyncMock(return_value=QuotaResourceStatus(limited=True))

        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ai_credits"] == {"exhausted": True, "used_usd": None, "limit_usd": None, "breakdown": None}
        assert data["is_rate_limited"] is True

    def test_ai_credits_reflects_resolver_for_billable_product(self, authenticated_usage_client: TestClient) -> None:
        from llm_gateway.services.quota_resolver import QuotaResourceStatus

        app = authenticated_usage_client.app
        resolver_mock = AsyncMock(return_value=QuotaResourceStatus(limited=True))
        app.state.quota_resolver.get_resource_status = resolver_mock

        response = authenticated_usage_client.get(
            "/v1/usage/slack_app",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ai_credits"] == {"exhausted": True, "used_usd": None, "limit_usd": None, "breakdown": None}
        assert data["is_rate_limited"] is True
        assert resolver_mock.call_args.args[0] == "ai_credits"

    def test_ai_credits_carries_org_spend_numbers(self, authenticated_usage_client: TestClient) -> None:
        """PostHog Desktop renders "used $X of $Y" (titlebar, plans page) off these
        numbers; None must stay None so clients read unknown, not $0."""
        from llm_gateway.services.quota_resolver import QuotaResourceStatus

        app = authenticated_usage_client.app
        app.state.quota_resolver.get_resource_status = AsyncMock(
            return_value=QuotaResourceStatus(limited=False, used_usd=12.4, limit_usd=50.0)
        )

        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        assert response.json()["ai_credits"] == {
            "exhausted": False,
            "used_usd": 12.4,
            "limit_usd": 50.0,
            "breakdown": None,
        }

    def test_posthog_code_includes_optional_component_breakdown(
        self,
        authenticated_usage_client: TestClient,
    ) -> None:
        from llm_gateway.services.quota_resolver import QuotaResourceStatus

        component_breakdown: dict[str, object] = {
            "token_credits": 1234,
            "compute_credits": 67,
            "cpu_millicore_seconds": 9_876_543_210,
            "memory_mib_seconds": 7_654_321_098,
        }
        authenticated_usage_client.app.state.quota_resolver.get_resource_status = AsyncMock(
            return_value=QuotaResourceStatus(
                limited=False,
                used_usd=13.01,
                limit_usd=20.0,
                posthog_desktop_usage=component_breakdown,
            )
        )
        data = authenticated_usage_client.get(
            "/v1/usage/posthog_code", headers={"Authorization": "Bearer phx_test"}
        ).json()

        assert data["ai_credits"]["used_usd"] == 13.01
        assert data["ai_credits"]["limit_usd"] == 20.0
        assert data["ai_credits"]["breakdown"] == component_breakdown

    @pytest.mark.parametrize("billing_active", [True, False])
    def test_code_usage_subscribed_reflects_billing_bit(
        self, authenticated_usage_client: TestClient, billing_active: bool
    ) -> None:
        """Clients pick billing copy and hide the free-tier meter off this
        field, so it must carry the same bit enforcement reads."""
        from llm_gateway.services.quota_resolver import QuotaResourceStatus

        app = authenticated_usage_client.app
        app.state.quota_resolver.get_resource_status = AsyncMock(
            return_value=QuotaResourceStatus(limited=False, code_usage_billing_active=billing_active)
        )

        response = authenticated_usage_client.get(
            "/v1/usage/posthog_code",
            headers={"Authorization": "Bearer phx_test"},
        )
        assert response.status_code == 200
        assert response.json()["code_usage_subscribed"] is billing_active
