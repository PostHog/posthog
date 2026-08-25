from datetime import UTC, datetime
from typing import Any

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    IntervalType,
    MCPToolCallBreakdownItem,
    MCPToolCallBreakdownQuery,
    MCPToolCallsAndErrorsItem,
    MCPToolCallsAndErrorsQuery,
    PropertyOperator,
)

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.mcp_analytics.backend.hogql_queries.dashboard_series import (
    MCPToolCallBreakdownQueryRunner,
    MCPToolCallsAndErrorsQueryRunner,
)
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

    @parameterized.expand(
        [
            ("minute", IntervalType.MINUTE, "-1h", [("2026-07-21 11:10:00", 1)]),
            ("day", IntervalType.DAY, "-1d", [("2026-07-20 00:00:00", 1), ("2026-07-21 00:00:00", 2)]),
        ]
    )
    def test_relative_windows_follow_the_interval_granularity(
        self, _name: str, interval: IntervalType, date_from: str, expected: list[tuple[str, int]]
    ) -> None:
        # QueryDateRange only leaves a relative date_from untruncated at minute/second granularity.
        # Both directions matter here: "last hour" has to stay exact or it pulls in an extra chunk
        # of calls, while day and up has to cover whole days or the first bucket undercounts against
        # the wall-clock keys the client zero-fills with.
        with freeze_time("2026-07-21 18:30:00"):
            # 08:00 Pacific on the 20th: inside the truncated day window, outside an exact one.
            self._emit(timestamp=datetime(2026, 7, 20, 15, 0, tzinfo=UTC))
            # 10:15 Pacific: inside the truncated hour window (10:00), outside the exact one (10:30).
            self._emit(timestamp=datetime(2026, 7, 21, 17, 15, tzinfo=UTC))
            self._emit(timestamp=datetime(2026, 7, 21, 18, 10, tzinfo=UTC))

            results = self._run(
                MCPToolCallsAndErrorsQuery(
                    dateRange=DateRange(date_from=date_from),
                    interval=interval,
                )
            )

        assert [(r.bucket, r.successes) for r in results] == expected

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

    def test_excludes_calls_without_a_tool_name(self) -> None:
        self._emit(timestamp=datetime(2026, 7, 21, 18, 0, tzinfo=UTC))
        self._emit(timestamp=datetime(2026, 7, 21, 18, 0, tzinfo=UTC), tool_name="")

        results = self._run(
            MCPToolCallsAndErrorsQuery(dateRange=DateRange(date_from="2026-07-19", date_to="2026-07-23"))
        )

        assert [(r.bucket, r.successes) for r in results] == [("2026-07-21 00:00:00", 1)]


class TestMCPToolCallBreakdownQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.timezone = "US/Pacific"
        self.team.save()

    def _emit(self, *, timestamp: datetime, tool_name: str) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="d1",
            timestamp=timestamp,
            properties={"$session_id": "s1", "$mcp_tool_name": tool_name, "$mcp_is_error": False},
        )

    def _run(self, query: MCPToolCallBreakdownQuery) -> list[MCPToolCallBreakdownItem]:
        flush_persons_and_events()
        return MCPToolCallBreakdownQueryRunner(query=query, team=self.team).calculate().results

    def test_splits_calls_by_tool_within_each_bucket(self) -> None:
        self._emit(timestamp=datetime(2026, 7, 21, 2, 0, tzinfo=UTC), tool_name="query_run")
        self._emit(timestamp=datetime(2026, 7, 21, 18, 0, tzinfo=UTC), tool_name="query_run")
        self._emit(timestamp=datetime(2026, 7, 21, 19, 0, tzinfo=UTC), tool_name="dashboard_create")

        results = self._run(
            MCPToolCallBreakdownQuery(dateRange=DateRange(date_from="2026-07-19", date_to="2026-07-23"))
        )

        assert sorted((r.bucket, r.tool, r.calls) for r in results) == [
            ("2026-07-20 00:00:00", "query_run", 1),
            ("2026-07-21 00:00:00", "dashboard_create", 1),
            ("2026-07-21 00:00:00", "query_run", 1),
        ]

    def test_property_filters_scope_the_series(self) -> None:
        self._emit(timestamp=datetime(2026, 7, 21, 18, 0, tzinfo=UTC), tool_name="query_run")
        self._emit(timestamp=datetime(2026, 7, 21, 18, 0, tzinfo=UTC), tool_name="other_tool")

        results = self._run(
            MCPToolCallBreakdownQuery(
                dateRange=DateRange(date_from="2026-07-19", date_to="2026-07-23"),
                properties=[
                    EventPropertyFilter(key="$mcp_tool_name", value=["query_run"], operator=PropertyOperator.EXACT)
                ],
            )
        )

        assert [(r.tool, r.calls) for r in results] == [("query_run", 1)]


class TestMCPDashboardSeriesGate(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    # Every other test here calls calculate() with the flag already on, so a runner that lost its
    # validate_query_runner_access override would stay green while the generic /query/ endpoint
    # reached it ungated (the base implementation returns True).
    @parameterized.expand(
        [
            (MCPToolCallsAndErrorsQueryRunner, MCPToolCallsAndErrorsQuery()),
            (MCPToolCallBreakdownQueryRunner, MCPToolCallBreakdownQuery()),
        ]
    )
    def test_runner_gates_on_mcp_analytics_flag(self, runner_cls: Any, query: Any) -> None:
        runner = runner_cls(query=query, team=self.team, user=self.user)

        assert runner.validate_query_runner_access(self.user) is True

        with patch("posthoganalytics.feature_enabled", return_value=False):
            with self.assertRaises(UserAccessControlError):
                runner.validate_query_runner_access(self.user)

    # The runners' access check reads the token owner's RBAC, not the token's granted scopes, so a
    # kind registered on the generic query endpoint without a _QUERY_KIND_SCOPES entry is reachable
    # by any token holding only query:read.
    @parameterized.expand(
        [
            (kind, scopes, expected_status)
            for kind in ("MCPToolCallsAndErrorsQuery", "MCPToolCallBreakdownQuery", "MCPToolCategoryMapQuery")
            for scopes, expected_status in (
                (["query:read"], 403),
                (["mcp_analytics:read"], 403),
                (["query:read", "mcp_analytics:read"], 200),
            )
        ]
    )
    def test_query_endpoint_scope_parity_for_api_keys(self, kind: str, scopes: list[str], expected_status: int) -> None:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="test", user=self.user, secure_value=hash_key_value(value), scopes=scopes)

        response = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            {"query": {"kind": kind}},
            HTTP_AUTHORIZATION=f"Bearer {value}",
        )

        assert response.status_code == expected_status, response.json()
