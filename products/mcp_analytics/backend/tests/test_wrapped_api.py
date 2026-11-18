from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.mcp_analytics.backend.facade.contracts import MCP_ANALYTICS_WRAPPED_FEATURE_FLAG
from products.mcp_analytics.backend.models import MCPAnalyticsWrapped

CARDS: dict[str, Any] = {
    "intro": {"tracked_since": "2026-07", "server_count": 1},
    "tool_calls": {"total_calls": 365, "months": [{"month": "2026-07", "calls": 365}], "growth_multiple": None},
    "top_tools": {"tools": [{"tool": "get_forecast", "calls": 270}]},
    "apps": None,
    "labs": None,
    "models": None,
    "rush_hour": None,
    "reliability": {"success_rate": 0.9178, "struggling_tool": None},
    "speed": None,
    "archetype": {"archetype": "one_hit_wonder", "evidence": 0.7397},
}


class TestWrappedAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag_on = True
        flag_patcher = patch(
            "posthoganalytics.feature_enabled",
            side_effect=lambda key, *args, **kwargs: self.flag_on and key == MCP_ANALYTICS_WRAPPED_FEATURE_FLAG,
        )
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)

    def _store(self, status: MCPAnalyticsWrapped.Status, days_ago: int) -> None:
        with team_scope(self.team.id):
            MCPAnalyticsWrapped.objects.create(
                team=self.team,
                year=2026,
                status=status,
                schema_version=1,
                payload=CARDS if status == MCPAnalyticsWrapped.Status.READY else {},
                generated_at=timezone.now() - timedelta(days=days_ago),
            )

    def _get(self) -> Any:
        return self.client.get(f"/api/projects/{self.team.id}/mcp_analytics/wrapped/current/")

    def test_a_fresh_wrap_is_returned_with_its_cards(self) -> None:
        self._store(MCPAnalyticsWrapped.Status.READY, days_ago=3)

        response = self._get()

        assert response.status_code == 200, response.json()
        wrapped = response.json()["wrapped"]
        assert wrapped["year"] == 2026
        assert wrapped["cards"] == CARDS

    @parameterized.expand(
        [
            ("older_than_the_window", MCPAnalyticsWrapped.Status.READY, 15),
            ("ineligible", MCPAnalyticsWrapped.Status.INELIGIBLE, 1),
            ("failed", MCPAnalyticsWrapped.Status.FAILED, 1),
        ]
    )
    def test_no_wrap_to_show(self, _name: str, status: MCPAnalyticsWrapped.Status, days_ago: int) -> None:
        self._store(status, days_ago=days_ago)

        response = self._get()

        assert response.status_code == 200
        assert response.json() == {"wrapped": None}

    def test_the_flag_gates_the_endpoint(self) -> None:
        self._store(MCPAnalyticsWrapped.Status.READY, days_ago=1)
        self.flag_on = False

        assert self._get().status_code == 403
