from datetime import UTC, datetime
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.schema import DateRange, IntervalType, MCPDashboardComparison, MCPDashboardQuery, MCPDashboardSection

from posthog.hogql.constants import LimitContext

from products.mcp_analytics.backend.hogql_queries.dashboard_query import MCPDashboardQueryRunner
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin
from products.mcp_analytics.backend.wrapped.queries import WrappedPeriod, fetch_wrapped_aggregates

NOW = datetime(2026, 12, 2, 12, 0, tzinfo=UTC)
TIMEZONE = "US/Pacific"
SESSION_ID = "019abc12-3456-7def-8000-000000000001"
CLAUDE = {"$mcp_client_name": "claude-code", "$mcp_llm_model": "claude-sonnet-4-5"}
CURSOR = {"$mcp_client_name": "cursor", "$mcp_llm_model": "gpt-6.1-sol"}


class _WrappedEventsTestMixin:
    team: Any

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        self.team.timezone = TIMEZONE
        self.team.test_account_filters = [{"key": "internal", "type": "event", "operator": "is_not_set"}]
        self.team.test_account_filters_default_checked = True
        self.team.save()

    def _emit(self, timestamp: str, tool: str, count: int = 1, **properties: Any) -> None:
        for _ in range(count):
            _create_event(
                team=self.team,
                event="$mcp_tool_call",
                distinct_id="d1",
                timestamp=timestamp,
                properties={
                    "$session_id": SESSION_ID,
                    "$mcp_source": "posthog_mcp_analytics",
                    "$mcp_server_name": "weather",
                    "$mcp_tool_name": tool,
                    **properties,
                },
            )

    def _seed_year(self) -> None:
        # US/Pacific: 2026-07-14T23:30:00Z is Jul 14, 16:30, a Tuesday.
        self._emit("2026-07-14T23:30:00Z", "get_forecast", 120, **CLAUDE, **{"$mcp_duration_ms": 100})
        self._emit("2026-08-11T23:30:00Z", "get_forecast", 150, **CLAUDE, **{"$mcp_duration_ms": 120})
        self._emit("2026-08-12T17:00:00Z", "list_alerts", 40, **CURSOR, **{"$mcp_duration_ms": 30})
        self._emit(
            "2026-09-08T23:30:00Z",
            "exec",
            30,
            **CLAUDE,
            **{"$mcp_exec_verb": "call", "$mcp_exec_target_tool": "create_alert", "$mcp_is_error": True},
        )
        self._emit("2026-09-08T23:40:00Z", "exec", 25, **CLAUDE, **{"$mcp_exec_verb": "search"})
        # Internal traffic, which the project's default test account filter drops.
        self._emit("2026-09-09T18:00:00Z", "get_forecast", 500, **CLAUDE, **{"internal": True})
        # Dec 1 00:30 in US/Pacific, so after the period ends even though it is still Nov 30 nowhere else.
        self._emit("2026-12-01T08:30:00Z", "get_forecast", 500, **CLAUDE)
        flush_persons_and_events()


@time_machine.travel(NOW, tick=False)
class TestWrappedQueries(_WrappedEventsTestMixin, _MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _dashboard(self, section: MCPDashboardSection) -> Any:
        response = MCPDashboardQueryRunner(
            query=MCPDashboardQuery(
                sections=[section],
                dateRange=DateRange(date_from="2026-01-01", date_to="2026-11-30"),
                filterTestAccounts=True,
                interval=IntervalType.MONTH,
                comparison=MCPDashboardComparison(
                    dateFrom="2026-01-01T08:00:00.000Z", currentStartBucket="2026-01-01 00:00:00"
                ),
            ),
            team=self.team,
            user=self.user,
            limit_context=LimitContext.QUERY_ASYNC,
        ).calculate()
        result = response.results[section.value]
        assert result.error is None, result.error
        return result.results

    def test_aggregates_count_tools_and_harnesses_like_the_dashboard(self) -> None:
        self._seed_year()

        aggregates = fetch_wrapped_aggregates(self.team, WrappedPeriod.for_year(self.team, 2026))

        tool_rows = self._dashboard(MCPDashboardSection.TOOL_ROWS)
        dashboard_tools = {row[0]: row[1] for row in tool_rows if row[-1] == "calls"}
        assert {row.key: row.calls for row in aggregates.tools} == dashboard_tools
        assert dashboard_tools == {"get_forecast": 270, "list_alerts": 40, "create_alert": 30, "exec": 25}

        harness_rows = self._dashboard(MCPDashboardSection.HARNESS_ROWS)
        dashboard_harnesses = {row.harness: row.total_calls for row in harness_rows}
        assert {row.key: row.calls for row in aggregates.harnesses} == dashboard_harnesses

        assert aggregates.total.calls == 365
        assert aggregates.total.errors == 30
        assert {row.key: row.calls for row in aggregates.labs} == {"Anthropic": 325, "OpenAI": 40}
        assert {row.key: row.calls for row in aggregates.model_families} == {"Claude Sonnet": 325, "GPT-6": 40}
        assert [(row.key, row.calls) for row in aggregates.months] == [
            ("2026-07-01", 120),
            ("2026-08-01", 190),
            ("2026-09-01", 55),
        ]
        assert {row.key: row.calls for row in aggregates.week_hours} == {"216": 325, "310": 40}
