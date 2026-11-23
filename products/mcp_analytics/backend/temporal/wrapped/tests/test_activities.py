from datetime import UTC, datetime

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.models.team import Team

from products.event_definitions.backend.models.event_definition import EventDefinition
from products.mcp_analytics.backend.models import MCPAnalyticsWrapped
from products.mcp_analytics.backend.temporal.wrapped.activities import _generate, wrapped_team_ids


class TestWrappedTeamDiscovery(BaseTest):
    def _team(self, name: str, event: str, last_seen_at: datetime) -> Team:
        team = Team.objects.create(organization=self.organization, name=name)
        EventDefinition.objects.create(team=team, name=event, last_seen_at=last_seen_at)
        return team

    def test_only_projects_with_tool_calls_this_year(self) -> None:
        this_year = self._team("this year", "$mcp_tool_call", datetime(2026, 3, 1, tzinfo=UTC))
        self._team("last year", "$mcp_tool_call", datetime(2025, 12, 30, tzinfo=UTC))
        self._team("pageviews only", "$pageview", datetime(2026, 3, 1, tzinfo=UTC))
        parent = Team.objects.create(organization=self.organization, name="parent")
        child = Team.objects.create(
            organization=self.organization, project=parent.project, name="child", parent_team=parent
        )
        EventDefinition.objects.create(
            team=child, project=parent.project, name="$mcp_tool_call", last_seen_at=datetime(2026, 3, 1, tzinfo=UTC)
        )
        first = Team.objects.create(organization=self.organization, name="first")
        second = Team.objects.create(organization=self.organization, project=first.project, name="second")
        EventDefinition.objects.create(
            team=second, project=first.project, name="$mcp_tool_call", last_seen_at=datetime(2026, 3, 1, tzinfo=UTC)
        )

        assert wrapped_team_ids(2026) == sorted([this_year.id, parent.id, first.id, second.id])


class TestGenerateWrapped(ClickhouseTestMixin, BaseTest):
    def test_generating_a_project_stores_its_snapshot(self) -> None:
        assert _generate(self.team.id, 2026) == MCPAnalyticsWrapped.Status.INELIGIBLE

        assert MCPAnalyticsWrapped.objects.unscoped().filter(team=self.team, year=2026).exists()
