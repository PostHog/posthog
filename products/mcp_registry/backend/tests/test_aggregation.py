from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event

from products.mcp_registry.backend.aggregation import aggregate_team, discover_measured_teams
from products.mcp_registry.backend.models import MCPMeasuredStats, MCPRegistryServer, MCPRegistryTool


def _tool_call(team: Any, session_id: str, **properties: Any) -> None:
    _create_event(
        team=team,
        event="$mcp_tool_call",
        distinct_id="agent-user",
        properties={
            "$mcp_source": "posthog_mcp_analytics",
            "$mcp_server_name": "PostHog",
            "$mcp_session_id": session_id,
            "$mcp_client_name": "Claude Code",
            "$mcp_is_error": False,
            **properties,
        },
    )


class TestAggregation(ClickhouseTestMixin, BaseTest):
    def test_aggregate_team_rolls_up_stats_and_resolves_effective_tools(self) -> None:
        official = MCPRegistryServer.objects.create(
            registry_name="io.github.PostHog/mcp", display_name="PostHog MCP Server", listed_in_registry=True
        )
        _tool_call(self.team, "s1", **{"$mcp_tool_name": "execute-sql", "$mcp_intent": "check error volume"})
        # Single-exec call: must roll up under the inner tool, not under "exec".
        _tool_call(
            self.team,
            "s1",
            **{"$mcp_tool_name": "exec", "$mcp_exec_tool_call_name": "execute-sql", "$mcp_is_error": True},
        )
        _tool_call(self.team, "s2", **{"$mcp_tool_name": "docs-search", "$mcp_intent": "find docs"})
        # Different SDK source and missing server name must both be ignored.
        _tool_call(self.team, "s3", **{"$mcp_tool_name": "noise", "$mcp_source": "other_sdk"})
        _tool_call(self.team, "s3", **{"$mcp_tool_name": "noise", "$mcp_server_name": ""})

        processed = aggregate_team(self.team)

        assert processed == 1
        stats = MCPMeasuredStats.objects.get(team_id=self.team.id, server_name="PostHog")
        assert stats.server == official
        assert stats.link_method == "override"
        assert (stats.calls, stats.sessions, stats.errors) == (3, 2, 1)
        assert stats.distinct_tools == 2
        assert round(stats.intent_coverage_pct) == 67
        by_name = {row["name"]: row for row in stats.tool_stats}
        assert by_name["execute-sql"]["calls"] == 2
        assert by_name["execute-sql"]["errors"] == 1
        assert by_name["docs-search"]["calls"] == 1

        official.refresh_from_db()
        assert official.is_measured is True
        assert set(
            MCPRegistryTool.objects.filter(server=official, source="analytics").values_list("name", flat=True)
        ) == {"execute-sql", "docs-search"}

    def test_discover_measured_teams_finds_teams_with_new_sdk_traffic(self) -> None:
        _tool_call(self.team, "s1", **{"$mcp_tool_name": "execute-sql"})

        assert self.team.id in discover_measured_teams()
