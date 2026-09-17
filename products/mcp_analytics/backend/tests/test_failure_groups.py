from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import DateRange, MCPFailureGroup, MCPFailureGroupsQuery

from products.mcp_analytics.backend.hogql_queries.failure_groups import MCPFailureGroupsQueryRunner
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin

NOW = datetime.now(tz=UTC)


class TestMCPFailureGroupsQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._known_distinct_ids: set[str] = set()

    def _emit(
        self,
        *,
        distinct_id: str,
        session_id: str,
        timestamp: datetime,
        tool: str = "query_run",
        is_error: bool = False,
        error_type: str = "internal",
        error_message: str = "Something went wrong",
        properties: dict[str, Any] | None = None,
    ) -> None:
        if distinct_id not in self._known_distinct_ids:
            _create_person(distinct_ids=[distinct_id], team=self.team, properties={})
            self._known_distinct_ids.add(distinct_id)
        error_properties = {"$mcp_error_type": error_type, "$mcp_error_message": error_message} if is_error else {}
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties={
                "$session_id": session_id,
                "$mcp_tool_name": tool,
                "$mcp_is_error": is_error,
                **error_properties,
                **(properties or {}),
            },
        )

    def _groups(self, limit: int | None = None) -> list[MCPFailureGroup]:
        runner = MCPFailureGroupsQueryRunner(
            query=MCPFailureGroupsQuery(
                dateRange=DateRange(date_from="-7d"),
                **({"limit": limit} if limit is not None else {}),
            ),
            team=self.team,
        )
        return runner.calculate().results

    def test_ranks_groups_by_sessions_affected_desc(self) -> None:
        # Group "a" fails across three sessions, group "b" across one: ranking, not raw call
        # count, must put "a" first even though a naive count() would tie them differently.
        for i, session_id in enumerate(["s1", "s2", "s3"]):
            self._emit(
                distinct_id=f"d{i}",
                session_id=session_id,
                timestamp=NOW - timedelta(hours=i),
                tool="tool_a",
                is_error=True,
                error_message="tool a failed",
            )
        self._emit(
            distinct_id="d9",
            session_id="s9",
            timestamp=NOW,
            tool="tool_b",
            is_error=True,
            error_message="tool b failed",
        )
        flush_persons_and_events()

        groups = self._groups()

        assert [g.tool for g in groups] == ["tool_a", "tool_b"]
        assert groups[0].sessions == 3
        assert groups[0].calls == 3
        assert groups[0].people == 3
        assert groups[1].sessions == 1

    @parameterized.expand(
        [
            (
                "differ_only_by_uuid",
                "Failed to fetch resource 6ba7b810-9dad-11d1-80b4-00c04fd430c8",
                "Failed to fetch resource 3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "Failed to fetch resource {id}",
            ),
            (
                "differ_only_by_digit_run",
                "Row 12345 not found",
                "Row 987654 not found",
                "Row {n} not found",
            ),
        ]
    )
    def test_message_normalization_collapses_ids_and_digit_runs(
        self, _name: str, message_a: str, message_b: str, expected_normalized: str
    ) -> None:
        self._emit(distinct_id="d1", session_id="s1", timestamp=NOW, is_error=True, error_message=message_a)
        self._emit(distinct_id="d2", session_id="s2", timestamp=NOW, is_error=True, error_message=message_b)
        flush_persons_and_events()

        groups = self._groups()

        assert len(groups) == 1
        assert groups[0].message == expected_normalized
        assert groups[0].calls == 2
        assert groups[0].sessions == 2

    @parameterized.expand(
        [
            ("retried_and_succeeded", "query_run", False, "next_retried_succeeded_pct"),
            # The retry's own failure gets a distinct message so it groups separately from the
            # original failure: otherwise it would join the same output row and count its own
            # (nonexistent) next action as "ended", diluting the percentage under test.
            ("retried_and_failed_again", "query_run", True, "next_retried_failed_pct"),
            ("switched_to_a_different_tool", "insight_get", False, "next_switched_pct"),
        ]
    )
    def test_next_action_outcome_after_a_failing_call(
        self, _name: str, next_tool: str, next_is_error: bool, expected_field: str
    ) -> None:
        self._emit(
            distinct_id="d1",
            session_id="s1",
            timestamp=NOW - timedelta(minutes=1),
            tool="query_run",
            is_error=True,
            error_message="original failure",
        )
        self._emit(
            distinct_id="d1",
            session_id="s1",
            timestamp=NOW,
            tool=next_tool,
            is_error=next_is_error,
            error_message="retry failure",
        )
        flush_persons_and_events()

        groups = {g.message: g for g in self._groups()}
        original = groups["original failure"]

        outcomes = {
            "next_retried_succeeded_pct": original.next_retried_succeeded_pct,
            "next_retried_failed_pct": original.next_retried_failed_pct,
            "next_switched_pct": original.next_switched_pct,
            "next_ended_pct": original.next_ended_pct,
        }
        for field, value in outcomes.items():
            assert value == (100.0 if field == expected_field else 0.0), outcomes

    def test_next_action_outcome_when_the_session_ends(self) -> None:
        self._emit(distinct_id="d1", session_id="s1", timestamp=NOW, tool="query_run", is_error=True)
        flush_persons_and_events()

        groups = self._groups()

        assert len(groups) == 1
        assert groups[0].next_ended_pct == 100.0
        assert groups[0].next_retried_succeeded_pct == 0.0
        assert groups[0].next_retried_failed_pct == 0.0
        assert groups[0].next_switched_pct == 0.0

    def test_sessionless_calls_do_not_read_as_each_others_retry(self) -> None:
        # Two people whose SDK sent no session id: without a per-call journey they would share
        # one partition and the second call would read as the first one's retry.
        self._emit(distinct_id="d1", session_id="", timestamp=NOW, tool="query_run", is_error=True)
        self._emit(
            distinct_id="d2", session_id="", timestamp=NOW + timedelta(seconds=5), tool="query_run", is_error=True
        )
        flush_persons_and_events()

        groups = self._groups()

        assert len(groups) == 1
        assert groups[0].calls == 2
        assert groups[0].next_ended_pct == 100.0
        assert groups[0].next_retried_failed_pct == 0.0

    @parameterized.expand(
        [
            ("unset_defaults_to_five", None, 5),
            ("below_one_clamps_to_one", 0, 1),
            ("above_fifty_clamps_to_fifty", 1000, 50),
            ("within_bounds_passes_through", 20, 20),
        ]
    )
    def test_limit_is_bounded_between_one_and_fifty(self, _name: str, requested: int | None, expected: int) -> None:
        runner = MCPFailureGroupsQueryRunner(
            query=MCPFailureGroupsQuery(dateRange=DateRange(date_from="-7d"), limit=requested),
            team=self.team,
        )
        assert runner.limit == expected
