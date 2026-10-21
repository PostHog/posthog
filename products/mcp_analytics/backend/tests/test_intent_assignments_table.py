from datetime import UTC, datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.models import Team

from products.mcp_analytics.backend.facade.clickhouse_schema import MCP_INTENT_ASSIGNMENTS_WRITABLE_TABLE


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
        "timestamp": datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC),
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

    def test_latest_run_wins_for_the_same_intent(self) -> None:
        _insert_assignment(self.team.pk, "a" * 64, "topic-1", run_id="run-1")
        _insert_assignment(
            self.team.pk,
            "a" * 64,
            "topic-2",
            run_id="run-2",
            timestamp=datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC),
        )

        response = execute_hogql_query(
            query="SELECT argMax(topic_id, timestamp), count() FROM mcp_intent_assignments GROUP BY intent_hash",
            team=self.team,
        )

        assert response.results == [("topic-2", 2)]

    def test_other_teams_rows_are_invisible(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        _insert_assignment(other_team.pk, "c" * 64, "topic-9")
        _insert_assignment(self.team.pk, "a" * 64, "topic-1")

        response = execute_hogql_query(query="SELECT intent_hash FROM mcp_intent_assignments", team=self.team)

        assert response.results == [("a" * 64,)]
