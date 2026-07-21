from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    IntervalType,
    MCPToolCategoriesQuery,
    MCPToolCategoryCountsQuery,
    MCPToolQualityDailyStatsQuery,
    MCPToolQualityRowsQuery,
)

from posthog.rbac.user_access_control import UserAccessControlError

from products.mcp_analytics.backend.hogql_queries.tool_quality_tables import (
    MCPToolCategoriesQueryRunner,
    MCPToolCategoryCountsQueryRunner,
    MCPToolQualityDailyStatsQueryRunner,
    MCPToolQualityRowsQueryRunner,
)
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin

NEW_SDK_SOURCE = "posthog_mcp_analytics"


def _emit(
    team: Any,
    *,
    tool_name: str = "query_run",
    category: str | None = None,
    is_error: bool = False,
    duration_ms: float = 100,
    session_id: str = "s1",
    distinct_id: str = "d1",
    timestamp: datetime | None = None,
) -> None:
    properties: dict[str, Any] = {
        "$mcp_tool_name": tool_name,
        "$mcp_source": NEW_SDK_SOURCE,
        "$mcp_is_error": is_error,
        "$mcp_duration_ms": duration_ms,
        "$session_id": session_id,
    }
    if category is not None:
        properties["$mcp_tool_category"] = category
    _create_event(
        team=team,
        event="$mcp_tool_call",
        distinct_id=distinct_id,
        timestamp=timestamp or datetime.now(tz=UTC),
        properties=properties,
    )


class TestMCPToolQualityRowsQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _run(self, categories: list[str] | None = None) -> list[Any]:
        runner = MCPToolQualityRowsQueryRunner(
            query=MCPToolQualityRowsQuery(dateRange=DateRange(date_from="-7d"), categories=categories),
            team=self.team,
        )
        return runner.calculate().results

    def test_one_row_per_tool_ordered_by_calls_with_error_rate(self) -> None:
        _emit(self.team, tool_name="query_run", is_error=False)
        _emit(self.team, tool_name="query_run", is_error=True)
        _emit(self.team, tool_name="insight_get", is_error=False)
        flush_persons_and_events()

        rows = self._run()

        assert [r.tool for r in rows] == ["query_run", "insight_get"]
        assert rows[0].total_calls == 2
        assert rows[0].errors == 1
        assert rows[0].error_rate_pct == 50.0

    def test_category_filter_narrows_the_rows(self) -> None:
        _emit(self.team, tool_name="query_run", category="Data")
        _emit(self.team, tool_name="insight_get", category="Insights")
        flush_persons_and_events()

        rows = self._run(categories=["Data"])

        assert [r.tool for r in rows] == ["query_run"]


class TestMCPToolQualityDailyStatsQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def test_buckets_by_hour_when_interval_is_hour(self) -> None:
        now = datetime.now(tz=UTC)
        _emit(self.team, timestamp=now - timedelta(hours=1, minutes=30))
        _emit(self.team, timestamp=now - timedelta(minutes=5))
        flush_persons_and_events()

        runner = MCPToolQualityDailyStatsQueryRunner(
            query=MCPToolQualityDailyStatsQuery(dateRange=DateRange(date_from="-6h"), interval=IntervalType.HOUR),
            team=self.team,
        )
        rows = runner.calculate().results

        assert len(rows) == 2
        assert rows[0].day < rows[1].day

    def test_tool_name_scopes_the_series(self) -> None:
        _emit(self.team, tool_name="query_run")
        _emit(self.team, tool_name="insight_get")
        flush_persons_and_events()

        runner = MCPToolQualityDailyStatsQueryRunner(
            query=MCPToolQualityDailyStatsQuery(dateRange=DateRange(date_from="-7d"), toolName="query_run"),
            team=self.team,
        )
        rows = runner.calculate().results

        assert sum(r.calls for r in rows) == 1


class TestMCPToolCategoryCountsQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def test_counts_per_category_including_uncategorized(self) -> None:
        _emit(self.team, category="Data")
        _emit(self.team, category="Data")
        _emit(self.team, category=None)  # uncategorized still counts toward the denominator
        flush_persons_and_events()

        runner = MCPToolCategoryCountsQueryRunner(
            query=MCPToolCategoryCountsQuery(dateRange=DateRange(date_from="-7d")),
            team=self.team,
        )
        counts = {r.category: r.calls for r in runner.calculate().results}

        assert counts["Data"] == 2
        assert sum(counts.values()) == 3


class TestMCPToolCategoriesQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def test_distinct_sorted_categories_excludes_empty(self) -> None:
        _emit(self.team, category="Insights")
        _emit(self.team, category="Data")
        _emit(self.team, category="Data")
        _emit(self.team, category=None)
        flush_persons_and_events()

        runner = MCPToolCategoriesQueryRunner(
            query=MCPToolCategoriesQuery(dateRange=DateRange(date_from="-7d")),
            team=self.team,
        )
        categories = [r.category for r in runner.calculate().results]

        assert categories == ["Data", "Insights"]


class TestMCPToolQualityGate(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    # The whole point of the migration: each kind gates on `mcp-analytics`, so the generic /query/
    # endpoint can't reach it without the flag. Every other test here calls calculate() with the flag
    # already on, so a runner that lost its validate_query_runner_access override would stay green.
    @parameterized.expand(
        [
            (MCPToolQualityRowsQueryRunner, MCPToolQualityRowsQuery()),
            (MCPToolQualityDailyStatsQueryRunner, MCPToolQualityDailyStatsQuery()),
            (MCPToolCategoryCountsQueryRunner, MCPToolCategoryCountsQuery()),
            (MCPToolCategoriesQueryRunner, MCPToolCategoriesQuery()),
        ]
    )
    def test_runner_gates_on_mcp_analytics_flag(self, runner_cls: Any, query: Any) -> None:
        runner = runner_cls(query=query, team=self.team, user=self.user)

        assert runner.validate_query_runner_access(self.user) is True

        with patch("posthoganalytics.feature_enabled", return_value=False):
            with self.assertRaises(UserAccessControlError):
                runner.validate_query_runner_access(self.user)
