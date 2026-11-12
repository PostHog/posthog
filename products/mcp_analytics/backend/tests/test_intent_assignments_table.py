from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute

from products.mcp_analytics.backend.facade.clickhouse_schema import MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE

# ClickHouse applies the table TTL with its own clock, so fixtures stay relative to now.
OTHER_TEAM_ID = 10**9


def _now() -> datetime:
    return datetime.now(tz=UTC).replace(microsecond=0)


def _insert_assignment(team_id: int, intent_hash: str, topic_id: str | None, **overrides) -> None:
    row = {
        "team_id": team_id,
        "intent_hash": intent_hash,
        "run_id": "run-1",
        "topic_id": topic_id,
        "distance": 0.1,
        "x": 1.0,
        "y": -1.0,
        "is_outlier": 0,
        "intent_text": "list feature flags",
        "calls_in_run": 3,
        "timestamp": _now() - timedelta(days=1),
        **overrides,
    }
    sync_execute(
        f"""
        INSERT INTO {MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE}
        (team_id, intent_hash, run_id, topic_id, distance, x, y, is_outlier, intent_text, calls_in_run, timestamp)
        VALUES
        """,
        [row],
    )


class TestMCPIntentAssignmentsTable(ClickhouseTestMixin, APIBaseTest):
    def test_rows_round_trip_through_hogql(self) -> None:
        _insert_assignment(self.team.pk, "a" * 64, "topic-1")
        _insert_assignment(self.team.pk, "b" * 64, None, is_outlier=1, distance=0.9)

        response = execute_hogql_query(
            query="""
                SELECT intent_hash, topic_id, is_outlier, round(toFloat(distance), 2), x, y, intent_text, calls_in_run
                FROM mcp_intent_assignments
                ORDER BY intent_hash
            """,
            team=self.team,
        )

        assert response.results == [
            ("a" * 64, "topic-1", 0, 0.1, 1.0, -1.0, "list feature flags", 3),
            ("b" * 64, None, 1, 0.9, 1.0, -1.0, "list feature flags", 3),
        ]

    def test_returns_only_the_latest_assignment_per_intent_across_partitions(self) -> None:
        # Rows in different monthly partitions never merge, so the read itself must dedupe.
        _insert_assignment(self.team.pk, "a" * 64, "topic-1", run_id="run-1", timestamp=_now() - timedelta(days=40))
        _insert_assignment(self.team.pk, "a" * 64, "topic-2", run_id="run-2", timestamp=_now() - timedelta(days=1))

        deduped = execute_hogql_query(
            query="SELECT intent_hash, topic_id, run_id FROM mcp_intent_assignments", team=self.team
        )
        raw = execute_hogql_query(query="SELECT count() FROM posthog.raw_mcp_intent_assignments", team=self.team)

        assert deduped.results == [("a" * 64, "topic-2", "run-2")]
        assert raw.results == [(2,)]

    def test_filters_apply_after_the_latest_assignment_is_chosen(self) -> None:
        _insert_assignment(self.team.pk, "a" * 64, "topic-1", run_id="run-1", timestamp=_now() - timedelta(days=2))
        _insert_assignment(self.team.pk, "a" * 64, "topic-2", run_id="run-2", timestamp=_now() - timedelta(days=1))

        response = execute_hogql_query(
            query="SELECT intent_hash FROM mcp_intent_assignments WHERE topic_id = 'topic-1'", team=self.team
        )

        assert response.results == []

    def test_other_teams_rows_are_invisible(self) -> None:
        _insert_assignment(OTHER_TEAM_ID, "c" * 64, "topic-9")
        _insert_assignment(self.team.pk, "a" * 64, "topic-1")

        response = execute_hogql_query(query="SELECT intent_hash FROM mcp_intent_assignments", team=self.team)
        raw = execute_hogql_query(query="SELECT intent_hash FROM posthog.raw_mcp_intent_assignments", team=self.team)

        assert response.results == [("a" * 64,)]
        assert raw.results == [("a" * 64,)]
