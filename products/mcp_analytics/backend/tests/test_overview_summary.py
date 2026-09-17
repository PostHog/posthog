from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import DateRange, MCPOverviewSummary, MCPOverviewSummaryQuery

from products.mcp_analytics.backend.hogql_queries.base import caller_kind_expr
from products.mcp_analytics.backend.hogql_queries.overview_summary import (
    NEW_PEOPLE_LOOKBACK_DAYS,
    MCPOverviewSummaryQueryRunner,
)
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin

NOW = datetime.now(tz=UTC)
WINDOW_FROM = NOW - timedelta(days=10)
WINDOW_TO = NOW
LOOKBACK_START = WINDOW_FROM - timedelta(days=NEW_PEOPLE_LOOKBACK_DAYS)


class TestMCPOverviewSummaryQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._known_distinct_ids: set[str] = set()

    def _emit(
        self,
        *,
        distinct_id: str,
        timestamp: datetime,
        is_error: bool = False,
        session_id: str = "s1",
        properties: dict[str, Any] | None = None,
    ) -> None:
        # A bare _create_event assigns each call its own random person_id unless a person for
        # the distinct_id was already staged, which would silently break every "person" and
        # "new vs. returning" assertion below (every call would look like a different person).
        if distinct_id not in self._known_distinct_ids:
            _create_person(distinct_ids=[distinct_id], team=self.team, properties={})
            self._known_distinct_ids.add(distinct_id)
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={
                "$session_id": session_id,
                "$mcp_tool_name": "query_run",
                "$mcp_is_error": is_error,
                **(properties or {}),
            },
        )

    def _summarize(self, **query_kwargs: Any) -> MCPOverviewSummary | None:
        runner = MCPOverviewSummaryQueryRunner(
            query=MCPOverviewSummaryQuery(
                dateRange=DateRange(date_from=WINDOW_FROM.isoformat(), date_to=WINDOW_TO.isoformat()),
                **query_kwargs,
            ),
            team=self.team,
        )
        results = runner.calculate().results
        return results[0] if results else None

    def test_empty_window_returns_no_results(self) -> None:
        assert self._summarize() is None

    def test_aggregates_calls_sessions_success_and_intent_pct(self) -> None:
        self._emit(distinct_id="d1", timestamp=NOW - timedelta(days=5), session_id="a")
        self._emit(
            distinct_id="d1",
            timestamp=NOW - timedelta(days=4),
            session_id="a",
            is_error=True,
            properties={"$mcp_intent": "find a churn cohort"},
        )
        self._emit(distinct_id="d2", timestamp=NOW - timedelta(days=3), session_id="b")
        flush_persons_and_events()

        summary = self._summarize()

        assert summary is not None
        assert summary.calls == 3
        assert summary.sessions == 2
        assert summary.success_pct == round(100 - (100 / 3), 1)
        assert summary.intent_pct == round(100 / 3, 1)
        assert summary.clients == 1

    @parameterized.expand(
        [
            # A person whose only call sits inside the window is new.
            ("only_call_in_window", [NOW - timedelta(days=5)], 1, 0),
            # A person with an earlier call inside the lookback horizon is returning.
            ("prior_call_within_lookback", [LOOKBACK_START + timedelta(days=5), NOW - timedelta(days=3)], 0, 1),
            # A person whose only prior call sits before the lookback horizon reads as new: the
            # classification is bounded to NEW_PEOPLE_LOOKBACK_DAYS, not full history.
            ("prior_call_before_lookback_horizon", [LOOKBACK_START - timedelta(days=5), NOW - timedelta(days=2)], 1, 0),
        ]
    )
    def test_classifies_new_vs_returning_within_lookback_window(
        self, _name: str, call_timestamps: list[datetime], expected_new: int, expected_returning: int
    ) -> None:
        for timestamp in call_timestamps:
            self._emit(distinct_id="d1", timestamp=timestamp)
        flush_persons_and_events()

        summary = self._summarize()

        assert summary is not None
        assert summary.new_people == expected_new
        assert summary.returning_people == expected_returning

    @parameterized.expand(
        [
            ("first_call_failed", True, False, 100.0),
            ("first_call_succeeded", False, True, 0.0),
        ]
    )
    def test_new_people_first_call_failed_pct_uses_only_the_first_call(
        self, _name: str, first_call_errors: bool, second_call_errors: bool, expected_pct: float
    ) -> None:
        # A regression here would count every errored call from a new person, not just their
        # first, which would double-count a person who fails, retries, and fails again.
        self._emit(distinct_id="d1", timestamp=NOW - timedelta(days=5), is_error=first_call_errors)
        self._emit(distinct_id="d1", timestamp=NOW - timedelta(days=4), is_error=second_call_errors)
        flush_persons_and_events()

        summary = self._summarize()

        assert summary is not None
        assert summary.new_people == 1
        assert summary.new_people_first_call_failed_pct == expected_pct

    @parameterized.expand([("unset_caller_kind", {}), ("all_caller_kind", {"callerKind": "all"})])
    def test_automation_totals_are_zero_unless_scoped_to_people(self, _name: str, query_kwargs: dict[str, Any]) -> None:
        self._emit(distinct_id="d1", timestamp=NOW - timedelta(days=5))
        self._emit(
            distinct_id="automation-1", timestamp=NOW - timedelta(days=5), properties={"$mcp_scope_preset": "scout"}
        )
        flush_persons_and_events()

        summary = self._summarize(**query_kwargs)

        assert summary is not None
        assert summary.automation_calls == 0
        assert summary.automation_sessions == 0

    def test_automation_only_window_still_reports_the_hidden_segment(self) -> None:
        self._emit(
            distinct_id="automation-1",
            timestamp=NOW - timedelta(days=5),
            session_id="b",
            properties={"$mcp_scope_preset": "scout"},
        )
        flush_persons_and_events()

        summary = self._summarize(callerKind="people")

        assert summary is not None
        assert (summary.people, summary.calls) == (0, 0)
        assert (summary.automation_calls, summary.automation_sessions) == (1, 1)

    @parameterized.expand([("typo", "peoples"), ("empty", ""), ("upper", "PEOPLE")])
    def test_rejects_unknown_caller_kinds(self, _name: str, kind: str) -> None:
        with self.assertRaises(ValueError):
            caller_kind_expr(kind)

    def test_automation_totals_populated_when_scoped_to_people(self) -> None:
        self._emit(distinct_id="d1", timestamp=NOW - timedelta(days=5), session_id="a")
        self._emit(
            distinct_id="automation-1",
            timestamp=NOW - timedelta(days=5),
            session_id="b",
            properties={"$mcp_scope_preset": "scout"},
        )
        self._emit(
            distinct_id="automation-1",
            timestamp=NOW - timedelta(days=4),
            session_id="b",
            properties={"$mcp_scope_preset": "scout"},
        )
        flush_persons_and_events()

        summary = self._summarize(callerKind="people")

        assert summary is not None
        assert summary.people == 1
        assert summary.automation_calls == 2
        assert summary.automation_sessions == 1
