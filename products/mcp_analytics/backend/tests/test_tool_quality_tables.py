from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    HogQLPropertyFilter,
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
from posthog.hogql.errors import QueryError

from products.mcp_analytics.backend.hogql_queries.base import shared_filter_exprs
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
    duration_ms: float | None = 100,
    session_id: str = "s1",
    mcp_session_id: str | None = None,
    distinct_id: str = "d1",
    timestamp: datetime | None = None,
) -> None:
    properties: dict[str, Any] = {
        "$mcp_tool_name": tool_name,
        "$mcp_source": NEW_SDK_SOURCE,
        "$mcp_is_error": is_error,
        "$session_id": session_id,
    }
    if mcp_session_id is not None:
        properties["$mcp_session_id"] = mcp_session_id
    if duration_ms is not None:
        properties["$mcp_duration_ms"] = duration_ms
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

    def test_previous_calls_and_current_metrics_split_by_window(self) -> None:
        now = datetime.now(tz=UTC)
        previous_window = now - timedelta(days=10)
        # Previous-window calls use a different session/user and are all errors, so any leakage
        # into the current-window aggregates (errors, users, sessions, first/last seen) shows up.
        for _ in range(3):
            _emit(
                self.team,
                tool_name="steady_tool",
                is_error=True,
                session_id="previous_session",
                distinct_id="previous_user",
                timestamp=previous_window,
            )
        _emit(self.team, tool_name="steady_tool", is_error=False, session_id="s1", distinct_id="d1", timestamp=now)
        _emit(self.team, tool_name="steady_tool", is_error=False, session_id="s1", distinct_id="d1", timestamp=now)
        flush_persons_and_events()

        row = self._run().results[0]

        assert row.tool == "steady_tool"
        assert row.total_calls == 2
        assert row.previous_calls == 3
        assert row.errors == 0
        assert row.error_rate_pct == 0
        assert row.users == 1
        assert row.sessions == 1

    @parameterized.expand(
        [
            ("seven_days", "-7d", datetime(2026, 9, 17, 6, tzinfo=UTC), datetime(2026, 9, 14, tzinfo=UTC)),
            ("fourteen_days", "-14d", datetime(2026, 9, 10, 6, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC)),
            ("thirty_days", "-30d", datetime(2026, 8, 25, 6, tzinfo=UTC), datetime(2026, 8, 10, tzinfo=UTC)),
        ]
    )
    @time_machine.travel(datetime(2026, 9, 24, 12, tzinfo=UTC), tick=False)
    def test_first_day_of_the_window_counts_only_as_current(
        self, _name: str, date_from: str, first_current_day: datetime, previous_day: datetime
    ) -> None:
        _emit(self.team, tool_name="steady_tool", timestamp=first_current_day)
        _emit(self.team, tool_name="steady_tool", timestamp=previous_day)
        flush_persons_and_events()

        runner = MCPToolQualityRowsQueryRunner(
            query=MCPToolQualityRowsQuery(dateRange=DateRange(date_from=date_from)), team=self.team
        )
        row = runner.calculate().results[0]

        assert (row.total_calls, row.previous_calls) == (1, 1)

    @time_machine.travel(datetime(2026, 9, 24, 12, tzinfo=UTC), tick=False)
    def test_windows_have_the_same_length_on_the_default_range(self) -> None:
        # -7d runs from Sep 17 00:00 to now, 180 hours. One call every hour on the half hour across
        # 360 hours puts 180 in each window only if the previous window is also 180 hours long.
        now = datetime(2026, 9, 24, 12, tzinfo=UTC)
        for hour in range(360):
            _emit(self.team, tool_name="steady_tool", timestamp=now - timedelta(hours=hour + 0.5))
        flush_persons_and_events()

        row = self._run().results[0]

        assert (row.total_calls, row.previous_calls) == (180, 180)

    @time_machine.travel(datetime(2026, 9, 10, 12, tzinfo=UTC), tick=False)
    def test_to_date_range_compares_against_the_same_part_of_the_previous_unit(self) -> None:
        _emit(self.team, tool_name="steady_tool", timestamp=datetime(2026, 8, 5, tzinfo=UTC))
        # Inside last month but after its first ten days, so outside the previous period.
        _emit(self.team, tool_name="steady_tool", timestamp=datetime(2026, 8, 20, tzinfo=UTC))
        _emit(self.team, tool_name="steady_tool", timestamp=datetime(2026, 9, 5, tzinfo=UTC))
        flush_persons_and_events()

        runner = MCPToolQualityRowsQueryRunner(
            query=MCPToolQualityRowsQuery(dateRange=DateRange(date_from="mStart")), team=self.team
        )
        row = runner.calculate().results[0]

        assert row.total_calls == 1
        assert row.previous_calls == 1

    def test_total_sessions_ignores_search_and_counts_each_session_once(self) -> None:
        _emit(self.team, tool_name="query_run", session_id="s1")
        _emit(self.team, tool_name="insight_get", session_id="s1")
        _emit(self.team, tool_name="insight_get", session_id="s2")
        flush_persons_and_events()

        response = MCPToolQualityRowsQueryRunner(
            query=MCPToolQualityRowsQuery(dateRange=DateRange(date_from="-7d"), search="query_run"), team=self.team
        ).calculate()

        assert [(row.tool, row.sessions) for row in response.results] == [("query_run", 1)]
        assert response.totalSessions == 2

    def test_sessions_count_the_mcp_session_id_when_there_is_no_posthog_session(self) -> None:
        _emit(self.team, tool_name="query_run", session_id="", mcp_session_id="conv_1")
        _emit(self.team, tool_name="query_run", session_id="", mcp_session_id="conv_2")
        flush_persons_and_events()

        response = self._run()

        assert (response.results[0].sessions, response.totalSessions) == (2, 2)

    def test_previous_sessions_and_previous_total_sessions(self) -> None:
        now = datetime.now(tz=UTC)
        previous_window = now - timedelta(days=10)
        _emit(self.team, tool_name="query_run", session_id="old_1", timestamp=previous_window)
        _emit(self.team, tool_name="insight_get", session_id="old_2", timestamp=previous_window)
        _emit(self.team, tool_name="insight_get", session_id="old_3", timestamp=previous_window)
        _emit(self.team, tool_name="query_run", session_id="new_1", timestamp=now)
        flush_persons_and_events()

        response = self._run()

        assert [(row.tool, row.sessions, row.previous_sessions) for row in response.results] == [("query_run", 1, 1)]
        assert (response.totalSessions, response.previousTotalSessions) == (1, 3)

    def test_previous_error_rate_and_p95_come_from_the_previous_window_only(self) -> None:
        now = datetime.now(tz=UTC)
        previous_window = now - timedelta(days=10)
        _emit(self.team, tool_name="steady_tool", is_error=True, duration_ms=1000, timestamp=previous_window)
        for _ in range(3):
            _emit(self.team, tool_name="steady_tool", duration_ms=1000, timestamp=previous_window)
        _emit(self.team, tool_name="steady_tool", duration_ms=100, timestamp=now)
        _emit(self.team, tool_name="new_tool", timestamp=now)
        _emit(self.team, tool_name="untimed_tool", duration_ms=None, timestamp=previous_window)
        _emit(self.team, tool_name="untimed_tool", timestamp=now)
        flush_persons_and_events()

        rows = {row.tool: row for row in self._run().results}

        assert (rows["steady_tool"].errors, rows["steady_tool"].previous_errors) == (0, 1)
        assert (rows["steady_tool"].p95_duration_ms, rows["steady_tool"].previous_p95_duration_ms) == (100, 1000)
        assert (rows["new_tool"].previous_errors, rows["new_tool"].previous_p95_duration_ms) == (0, None)
        # Previous calls exist but none carried a duration, so there is no previous p95 to compare.
        assert rows["untimed_tool"].previous_p95_duration_ms is None

    def test_tool_with_only_previous_calls_is_absent_and_excluded_from_total_count(self) -> None:
        now = datetime.now(tz=UTC)
        _emit(self.team, tool_name="old_only_tool", timestamp=now - timedelta(days=10))
        _emit(self.team, tool_name="current_tool", timestamp=now)
        flush_persons_and_events()

        response = self._run()

        assert [row.tool for row in response.results] == ["current_tool"]
        assert response.totalCount == 1
        assert response.results[0].previous_calls == 0

    @parameterized.expand(
        [
            # k is floored at 10 because these volumes are tiny.
            ("growth", 2, 6, 4 / 12),
            ("decline", 6, 2, -4 / 16),
            ("flat", 3, 3, 0.0),
            ("new", 0, 5, 5 / 10),
        ]
    )
    def test_trend_score(self, _name: str, previous: int, current: int, expected: float) -> None:
        now = datetime.now(tz=UTC)
        for _ in range(previous):
            _emit(self.team, tool_name="steady_tool", timestamp=now - timedelta(days=10))
        for _ in range(current):
            _emit(self.team, tool_name="steady_tool", timestamp=now)
        flush_persons_and_events()

        row = self._run().results[0]

        assert row.trend_score == pytest.approx(expected)

    def test_sort_by_trend_score_ranks_volume_weighted_surge_above_raw_percent(self) -> None:
        # Raw percent change favours tool_a (2900% vs 900%), but tool_a's growth is 1 -> 30 calls
        # while tool_b's is a real surge, 20 -> 200. The smoothed trend_score (k floored at 10
        # since total current-window calls here is small) ranks tool_b's larger absolute surge
        # above tool_a's tiny-volume spike: 180/30=6 vs 29/11=2.6.
        now = datetime.now(tz=UTC)
        previous_window = now - timedelta(days=10)
        _emit(self.team, tool_name="tool_a", timestamp=previous_window)
        for _ in range(30):
            _emit(self.team, tool_name="tool_a", timestamp=now)
        for _ in range(20):
            _emit(self.team, tool_name="tool_b", timestamp=previous_window)
        for _ in range(200):
            _emit(self.team, tool_name="tool_b", timestamp=now)
        flush_persons_and_events()

        runner = MCPToolQualityRowsQueryRunner(
            query=MCPToolQualityRowsQuery(
                dateRange=DateRange(date_from="-7d"), sortColumn="trend_score", sortDirection="DESC"
            ),
            team=self.team,
        )
        results = runner.calculate().results

        assert [(row.tool, row.total_calls, row.previous_calls) for row in results] == [
            ("tool_b", 200, 20),
            ("tool_a", 30, 1),
        ]


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

    def test_rejects_executable_property_filters(self) -> None:
        with self.assertRaisesRegex(QueryError, "Only event, person, and session property filters"):
            shared_filter_exprs(self.team, [HogQLPropertyFilter(key="1 = 1")], None)

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
