from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    IntervalType,
    MCPToolCategoriesQuery,
    MCPToolCategoryCountsQuery,
    MCPToolCategoryMapQuery,
    MCPToolQualityDailyStatsQuery,
    MCPToolQualityRowsQuery,
    MCPToolQualityRowsQueryResponse,
    PropertyOperator,
)

from posthog.hogql import ast

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.mcp_analytics.backend.hogql_queries.tool_quality_tables import (
    MCPToolCategoriesQueryRunner,
    MCPToolCategoryCountsQueryRunner,
    MCPToolCategoryMapQueryRunner,
    MCPToolQualityDailyStatsQueryRunner,
    MCPToolQualityRowsQueryRunner,
)
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin

NEW_SDK_SOURCE = "posthog_mcp_analytics"


def _emit(
    team: Any,
    *,
    tool_name: str = "query_run",
    exec_tool_name: str | None = None,
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
    if exec_tool_name is not None:
        properties["$mcp_exec_tool_call_name"] = exec_tool_name
    _create_event(
        team=team,
        event="$mcp_tool_call",
        distinct_id=distinct_id,
        timestamp=timestamp or datetime.now(tz=UTC),
        properties=properties,
    )


class TestMCPToolQualityRowsQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _run(self, categories: list[str] | None = None) -> MCPToolQualityRowsQueryResponse:
        runner = MCPToolQualityRowsQueryRunner(
            query=MCPToolQualityRowsQuery(dateRange=DateRange(date_from="-7d"), categories=categories),
            team=self.team,
        )
        return runner.calculate()

    def test_one_row_per_tool_ordered_by_calls_with_error_rate(self) -> None:
        _emit(self.team, tool_name="query_run", is_error=False)
        _emit(self.team, tool_name="query_run", is_error=True)
        _emit(self.team, tool_name="exec", exec_tool_name="query_run", is_error=False)
        _emit(self.team, tool_name="insight_get", is_error=False)
        flush_persons_and_events()

        rows = self._run().results

        assert [r.tool for r in rows] == ["query_run", "insight_get"]
        assert rows[0].total_calls == 3
        assert rows[0].errors == 1
        assert rows[0].error_rate_pct == 33.3

    def test_category_filter_narrows_the_rows(self) -> None:
        _emit(self.team, tool_name="query_run", category="Data")
        _emit(self.team, tool_name="insight_get", category="Insights")
        flush_persons_and_events()

        rows = self._run(categories=["Data"]).results

        assert [r.tool for r in rows] == ["query_run"]

    def test_search_sort_and_pagination_apply_to_all_matching_tools(self) -> None:
        for _ in range(3):
            _emit(self.team, tool_name="popular_tool")
        for _ in range(2):
            _emit(self.team, tool_name="steady_tool")
        _emit(self.team, tool_name="rare_target", is_error=True)
        flush_persons_and_events()

        first_page = MCPToolQualityRowsQueryRunner(
            query=MCPToolQualityRowsQuery(dateRange=DateRange(date_from="-7d"), limit=2),
            team=self.team,
        ).calculate()
        last_page = MCPToolQualityRowsQueryRunner(
            query=MCPToolQualityRowsQuery(dateRange=DateRange(date_from="-7d"), limit=2, offset=2),
            team=self.team,
        ).calculate()
        out_of_range_page = MCPToolQualityRowsQueryRunner(
            query=MCPToolQualityRowsQuery(dateRange=DateRange(date_from="-7d"), limit=2, offset=100),
            team=self.team,
        ).calculate()
        searched_runner = MCPToolQualityRowsQueryRunner(
            query=MCPToolQualityRowsQuery(dateRange=DateRange(date_from="-7d"), search="TARGET", limit=1),
            team=self.team,
        )
        searched_query = searched_runner.to_query()
        searched = searched_runner.calculate()
        highest_error_rate = MCPToolQualityRowsQueryRunner(
            query=MCPToolQualityRowsQuery(
                dateRange=DateRange(date_from="-7d"),
                sortColumn="error_rate_pct",
                sortDirection="DESC",
                limit=1,
            ),
            team=self.team,
        ).calculate()

        assert [row.tool for row in first_page.results] == ["popular_tool", "steady_tool"]
        assert first_page.totalCount == 3
        assert [row.tool for row in last_page.results] == ["rare_target"]
        assert last_page.totalCount == 3
        assert out_of_range_page.results == []
        assert out_of_range_page.totalCount == 3
        assert isinstance(searched_query, ast.SelectQuery)
        assert searched_query.having is None
        assert [row.tool for row in searched.results] == ["rare_target"]
        assert searched.totalCount == 1
        assert [row.tool for row in highest_error_rate.results] == ["rare_target"]


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
        _emit(self.team, tool_name="exec", exec_tool_name="query_run")
        _emit(self.team, tool_name="insight_get")
        flush_persons_and_events()

        runner = MCPToolQualityDailyStatsQueryRunner(
            query=MCPToolQualityDailyStatsQuery(dateRange=DateRange(date_from="-7d"), toolName="query_run"),
            team=self.team,
        )
        rows = runner.calculate().results

        assert sum(r.calls for r in rows) == 2


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


class TestMCPToolCategoryMapQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def test_pairs_are_deduped_and_skip_rows_missing_either_side(self) -> None:
        _emit(self.team, tool_name="query_run", category="Insights")
        _emit(self.team, tool_name="query_run", category="Insights")
        _emit(self.team, tool_name="docs_search", category="Data")
        # No category: the tool is real but unclassifiable, so it must not appear at all
        # rather than land under an empty-string category the scope selector would show.
        _emit(self.team, tool_name="orphan_tool", category=None)
        flush_persons_and_events()

        runner = MCPToolCategoryMapQueryRunner(
            query=MCPToolCategoryMapQuery(dateRange=DateRange(date_from="-7d")),
            team=self.team,
        )
        pairs = [(r.tool, r.category) for r in runner.calculate().results]

        assert pairs == [("docs_search", "Data"), ("query_run", "Insights")]

    def test_recategorised_tool_keeps_both_categories(self) -> None:
        # Filtering by either category has to keep finding the tool, so both rows survive
        # instead of one arbitrarily winning.
        _emit(self.team, tool_name="query_run", category="Insights")
        _emit(self.team, tool_name="query_run", category="SQL")
        flush_persons_and_events()

        runner = MCPToolCategoryMapQueryRunner(
            query=MCPToolCategoryMapQuery(dateRange=DateRange(date_from="-7d")),
            team=self.team,
        )
        pairs = [(r.tool, r.category) for r in runner.calculate().results]

        assert pairs == [("query_run", "Insights"), ("query_run", "SQL")]


def _setup_included_and_excluded_tools(team: Any) -> None:
    """One event on the shared property filter's match, one off it, to prove the filter
    reaches every runner below the same way it reaches the Tool quality rows table."""
    _emit(team, tool_name="included_tool", category="Data")
    _emit(team, tool_name="excluded_tool", category="Insights")


class TestMCPToolQualitySharedFilters(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    """Every runner here resolves its WHERE through `_named_tool_where` or applies
    `shared_filter_exprs` directly, so the dashboard's shared property filters and "Filter out
    internal and test users" switch (see hogql_queries/base.py) reach all of them. One
    parameterized case per runner proves that, rather than duplicating a property-filter test
    and a filterTestAccounts test per runner.
    """

    @parameterized.expand(
        [
            ("quality_rows", MCPToolQualityRowsQueryRunner, MCPToolQualityRowsQuery, len, 2, 1),
            (
                "quality_daily_stats",
                MCPToolQualityDailyStatsQueryRunner,
                MCPToolQualityDailyStatsQuery,
                lambda rows: sum(r.calls for r in rows),
                2,
                1,
            ),
            (
                "category_counts",
                MCPToolCategoryCountsQueryRunner,
                MCPToolCategoryCountsQuery,
                lambda rows: sum(r.calls for r in rows),
                2,
                1,
            ),
            (
                "categories",
                MCPToolCategoriesQueryRunner,
                MCPToolCategoriesQuery,
                lambda rows: {r.category for r in rows},
                {"Data", "Insights"},
                {"Data"},
            ),
        ]
    )
    def test_property_filter_and_test_accounts_narrow_the_results(
        self,
        _name: str,
        runner_cls: Any,
        query_cls: Any,
        metric_fn: Any,
        expected_unfiltered: Any,
        expected_filtered: Any,
    ) -> None:
        _setup_included_and_excluded_tools(self.team)
        flush_persons_and_events()

        def run(**filter_kwargs: Any) -> Any:
            query = query_cls(dateRange=DateRange(date_from="-7d"), **filter_kwargs)
            return metric_fn(runner_cls(query=query, team=self.team).calculate().results)

        assert run() == expected_unfiltered

        assert (
            run(
                properties=[
                    EventPropertyFilter(key="$mcp_tool_name", value=["included_tool"], operator=PropertyOperator.EXACT)
                ]
            )
            == expected_filtered
        )

        self.team.test_account_filters = [
            {"key": "$mcp_tool_name", "value": ["excluded_tool"], "operator": "is_not", "type": "event"}
        ]
        self.team.save()
        assert run(filterTestAccounts=True) == expected_filtered


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
            (MCPToolCategoryMapQueryRunner, MCPToolCategoryMapQuery()),
        ]
    )
    def test_runner_gates_on_mcp_analytics_flag(self, runner_cls: Any, query: Any) -> None:
        runner = runner_cls(query=query, team=self.team, user=self.user)

        assert runner.validate_query_runner_access(self.user) is True

        with patch("posthoganalytics.feature_enabled", return_value=False):
            with self.assertRaises(UserAccessControlError):
                runner.validate_query_runner_access(self.user)
