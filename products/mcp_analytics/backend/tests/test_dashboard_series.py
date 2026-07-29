from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    IntervalType,
    MCPToolCallsAndErrorsItem,
    MCPToolCallsAndErrorsQuery,
    PropertyOperator,
)

from posthog.rbac.user_access_control import UserAccessControlError

from products.mcp_analytics.backend.hogql_queries.dashboard_series import MCPToolCallsAndErrorsQueryRunner
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin


class TestMCPToolCallsAndErrorsQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.timezone = "US/Pacific"
        self.team.save()

    def _emit(
        self,
        *,
        timestamp: datetime,
        is_error: bool = False,
        tool_name: str = "query_run",
        extra: dict[str, Any] | None = None,
    ) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="d1",
            timestamp=timestamp,
            properties={
                "$session_id": "s1",
                "$mcp_tool_name": tool_name,
                "$mcp_is_error": is_error,
                **(extra or {}),
            },
        )

    def _run(self, query: MCPToolCallsAndErrorsQuery) -> list[MCPToolCallsAndErrorsItem]:
        flush_persons_and_events()
        return MCPToolCallsAndErrorsQueryRunner(query=query, team=self.team).calculate().results

    def test_buckets_in_team_timezone_as_naive_strings(self) -> None:
        # 19:00 Pacific on the 20th, which is the 21st in UTC. Bucketing in UTC would file it a day
        # late, and a zone-stamped bucket would not join the wall-clock keys the client generates.
        self._emit(timestamp=datetime(2026, 7, 21, 2, 0, tzinfo=UTC))
        self._emit(timestamp=datetime(2026, 7, 21, 18, 0, tzinfo=UTC), is_error=True)
        self._emit(timestamp=datetime(2026, 7, 21, 19, 0, tzinfo=UTC))

        results = self._run(
            MCPToolCallsAndErrorsQuery(dateRange=DateRange(date_from="2026-07-19", date_to="2026-07-23"))
        )

        assert [(r.bucket, r.successes, r.errors) for r in results] == [
            ("2026-07-20 00:00:00", 1, 0),
            ("2026-07-21 00:00:00", 1, 1),
        ]

    def test_buckets_by_hour_when_the_interval_asks_for_it(self) -> None:
        self._emit(timestamp=datetime(2026, 7, 21, 18, 15, tzinfo=UTC))
        self._emit(timestamp=datetime(2026, 7, 21, 19, 45, tzinfo=UTC))

        results = self._run(
            MCPToolCallsAndErrorsQuery(
                dateRange=DateRange(date_from="2026-07-21", date_to="2026-07-22"),
                interval=IntervalType.HOUR,
            )
        )

        assert [r.bucket for r in results] == ["2026-07-21 11:00:00", "2026-07-21 12:00:00"]

    def test_property_filters_scope_the_series(self) -> None:
        self._emit(timestamp=datetime(2026, 7, 21, 18, 0, tzinfo=UTC), tool_name="query_run")
        self._emit(timestamp=datetime(2026, 7, 21, 18, 0, tzinfo=UTC), tool_name="other_tool")

        results = self._run(
            MCPToolCallsAndErrorsQuery(
                dateRange=DateRange(date_from="2026-07-19", date_to="2026-07-23"),
                properties=[
                    EventPropertyFilter(key="$mcp_tool_name", value=["query_run"], operator=PropertyOperator.EXACT)
                ],
            )
        )

        assert [(r.bucket, r.successes) for r in results] == [("2026-07-21 00:00:00", 1)]

    def test_filter_test_accounts_applies_the_team_filters(self) -> None:
        self.team.test_account_filters = [
            {
                "key": "$mcp_tool_name",
                "value": ["internal_tool"],
                "operator": "is_not",
                "type": "event",
            }
        ]
        self.team.save()
        self._emit(timestamp=datetime(2026, 7, 21, 18, 0, tzinfo=UTC), tool_name="query_run")
        self._emit(timestamp=datetime(2026, 7, 21, 18, 0, tzinfo=UTC), tool_name="internal_tool")

        date_range = DateRange(date_from="2026-07-19", date_to="2026-07-23")
        unfiltered = self._run(MCPToolCallsAndErrorsQuery(dateRange=date_range))
        filtered = self._run(MCPToolCallsAndErrorsQuery(dateRange=date_range, filterTestAccounts=True))

        assert [r.successes for r in unfiltered] == [2]
        assert [r.successes for r in filtered] == [1]

    def test_gates_on_the_mcp_analytics_flag(self) -> None:
        # Every other test calls calculate() with the flag already on, so a runner that lost its
        # validate_query_runner_access override would stay green while the generic /query/ endpoint
        # reached it ungated (the base implementation returns True).
        runner = MCPToolCallsAndErrorsQueryRunner(query=MCPToolCallsAndErrorsQuery(), team=self.team, user=self.user)

        assert runner.validate_query_runner_access(self.user) is True

        with patch("posthoganalytics.feature_enabled", return_value=False):
            with self.assertRaises(UserAccessControlError):
                runner.validate_query_runner_access(self.user)

    def test_excludes_calls_without_a_tool_name(self) -> None:
        self._emit(timestamp=datetime(2026, 7, 21, 18, 0, tzinfo=UTC))
        self._emit(timestamp=datetime(2026, 7, 21, 18, 0, tzinfo=UTC), tool_name="")

        results = self._run(
            MCPToolCallsAndErrorsQuery(dateRange=DateRange(date_from="2026-07-19", date_to="2026-07-23"))
        )

        assert [(r.bucket, r.successes) for r in results] == [("2026-07-21 00:00:00", 1)]
