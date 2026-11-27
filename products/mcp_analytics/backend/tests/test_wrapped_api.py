from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.scoping import team_scope
from posthog.models.team import Team

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.access_control.backend.property_access_control import PropertyAccessLevel
from products.event_definitions.backend.models import PropertyDefinition
from products.mcp_analytics.backend.facade.contracts import MCP_ANALYTICS_WRAPPED_FEATURE_FLAG
from products.mcp_analytics.backend.models import MCPAnalyticsWrapped
from products.mcp_analytics.backend.wrapped.cards import SCHEMA_VERSION

CARDS: dict[str, Any] = {
    "intro": {"tracked_since": "2026-07", "server_count": 1},
    "tool_calls": {"total_calls": 365, "months": [{"month": "2026-07", "calls": 365}], "growth_multiple": None},
    "top_tools": {"tools": [{"tool": "get_forecast", "calls": 270}]},
    "apps": None,
    "labs": None,
    "models": None,
    "rush_hour": None,
    "reliability": {"success_rate": 0.9178, "most_reliable_tool": None, "struggling_tool": None},
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

    def _store(self, status: MCPAnalyticsWrapped.Status, days_ago: int, schema_version: int = SCHEMA_VERSION) -> None:
        with team_scope(self.team.id):
            MCPAnalyticsWrapped.objects.create(
                team=self.team,
                year=2026,
                status=status,
                schema_version=schema_version,
                payload=CARDS if status == MCPAnalyticsWrapped.Status.READY else {},
                generated_at=timezone.now() - timedelta(days=days_ago),
            )

    def _get(self, team_id: int | None = None) -> Any:
        return self.client.get(f"/api/projects/{team_id or self.team.id}/mcp_analytics/wrapped/current/")

    def _restrict(self, property_name: str) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name=property_name, property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(
            team=self.team, property_definition=definition, access_level=PropertyAccessLevel.NONE.value
        )

    def test_a_fresh_wrap_is_returned_with_its_cards(self) -> None:
        self._store(MCPAnalyticsWrapped.Status.READY, days_ago=3)

        response = self._get()

        assert response.status_code == 200, response.json()
        wrapped = response.json()["wrapped"]
        assert wrapped["year"] == 2026
        assert wrapped["cards"] == CARDS

    @parameterized.expand(
        [
            ("older_than_the_window", MCPAnalyticsWrapped.Status.READY, 15, SCHEMA_VERSION),
            ("ineligible", MCPAnalyticsWrapped.Status.INELIGIBLE, 1, SCHEMA_VERSION),
            ("failed", MCPAnalyticsWrapped.Status.FAILED, 1, SCHEMA_VERSION),
            ("an_older_card_shape", MCPAnalyticsWrapped.Status.READY, 1, SCHEMA_VERSION - 1),
        ]
    )
    def test_no_wrap_to_show(
        self, _name: str, status: MCPAnalyticsWrapped.Status, days_ago: int, schema_version: int
    ) -> None:
        self._store(status, days_ago=days_ago, schema_version=schema_version)

        response = self._get()

        assert response.status_code == 200
        assert response.json() == {"wrapped": None}

    @parameterized.expand(
        [
            ("tool_names_hidden", "$mcp_tool_name", False),
            ("models_hidden", "$mcp_llm_model", False),
            ("exec_verb_hidden", "$mcp_exec_verb", False),
            ("unrelated_property_hidden", "$mcp_intent", True),
        ]
    )
    def test_property_restrictions_hide_the_wrap(self, _name: str, restricted: str, wrap_shown: bool) -> None:
        self._store(MCPAnalyticsWrapped.Status.READY, days_ago=1)
        self._restrict(restricted)

        wrapped = self._get().json()["wrapped"]

        assert (wrapped is not None) is wrap_shown

    @parameterized.expand(
        [
            ("unrestricted", False),
            ("restricted_on_the_parent", True),
        ]
    )
    def test_a_child_environment_reads_its_parents_wrap(self, _name: str, restrict_parent: bool) -> None:
        self._store(MCPAnalyticsWrapped.Status.READY, days_ago=1)
        child = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="Child"
        )
        if restrict_parent:
            self._restrict("$mcp_tool_name")

        response = self._get(child.id)

        assert response.status_code == 200, response.json()
        wrapped = response.json()["wrapped"]
        if restrict_parent:
            assert wrapped is None
        else:
            assert wrapped["cards"] == CARDS

    @parameterized.expand(
        [
            ("mcp_analytics_denied_on_the_parent", "mcp_analytics", None),
            ("project_denied_on_the_parent", "project", "parent"),
        ]
    )
    def test_a_child_environment_grant_does_not_open_the_parents_wrap(
        self, _name: str, resource: str, resource_id: str | None
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self._store(MCPAnalyticsWrapped.Status.READY, days_ago=1)
        child = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="Child"
        )
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=str(self.team.id) if resource_id else None,
            access_level="none",
            organization_member=self.organization_membership,
        )
        AccessControl.objects.create(
            team=child,
            resource="mcp_analytics",
            access_level="editor",
            organization_member=self.organization_membership,
        )

        response = self._get(child.id)

        assert response.status_code == 403 or response.json()["wrapped"] is None, response.json()

    def test_the_flag_gates_the_endpoint(self) -> None:
        self._store(MCPAnalyticsWrapped.Status.READY, days_ago=1)
        self.flag_on = False

        assert self._get().status_code == 403
