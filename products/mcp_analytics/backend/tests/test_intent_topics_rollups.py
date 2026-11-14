from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.hogql.query import execute_hogql_query

from products.mcp_analytics.backend.intent_hash import intent_hash
from products.mcp_analytics.backend.intent_topics.corpus import HourlyCalls, fetch_hourly_calls
from products.mcp_analytics.backend.intent_topics.rollups import insert_hourly_calls, rebuild_topic_daily
from products.mcp_analytics.backend.tests.test_intent_assignments_table import _insert_assignment

OTHER_TEAM_ID = 10**9
DAY = datetime(2026, 10, 19, 0, 0, tzinfo=UTC)


class TestFetchHourlyCalls(ClickhouseTestMixin, APIBaseTest):
    def test_groups_by_hour_intent_and_tool_with_conversations(self) -> None:
        for minute, session in ((5, "s1"), (10, "s1"), (70, "s2")):
            _create_event(
                team=self.team,
                event="$mcp_tool_call",
                distinct_id="a",
                timestamp=DAY + timedelta(minutes=minute),
                properties={
                    "$mcp_tool_name": "query-trends",
                    "$mcp_intent": "plot signups",
                    "$mcp_session_id": session,
                },
            )
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="a",
            timestamp=DAY + timedelta(minutes=6),
            properties={"$mcp_tool_name": "query-funnel", "$mcp_intent": "plot signups", "$mcp_session_id": "s1"},
        )
        flush_persons_and_events()

        rows = fetch_hourly_calls(self.team, since=DAY, until=DAY + timedelta(hours=2))

        h = intent_hash("plot signups")
        assert [(r.hour.hour, r.hash == h, r.tool, r.calls, r.sessions) for r in rows] == [
            (0, True, "query-funnel", 1, 1),
            (0, True, "query-trends", 2, 1),
            (1, True, "query-trends", 1, 1),
        ]


class TestRebuildTopicDaily(ClickhouseTestMixin, APIBaseTest):
    def _hourly(self, hour: int, hash_: str, tool: str, calls: int, sessions: int = 1) -> HourlyCalls:
        return HourlyCalls(hour=DAY + timedelta(hours=hour), hash=hash_, tool=tool, calls=calls, sessions=sessions)

    def _daily(self) -> list[tuple]:
        return execute_hogql_query(
            query="SELECT toString(day), tool, topic_id, calls, sessions, outlier_calls, intents FROM mcp_intent_topic_daily ORDER BY tool, topic_id",
            team=self.team,
        ).results

    def test_sums_calls_per_tool_and_topic_with_unassigned_and_outliers(self) -> None:
        insert_hourly_calls(
            self.team.pk,
            [
                self._hourly(1, "h1", "query-trends", 3),
                self._hourly(2, "h1", "query-trends", 2),
                self._hourly(1, "h2", "query-trends", 4),
                self._hourly(1, "h3", "query-funnel", 1),
                self._hourly(1, "h4", "query-trends", 7),
            ],
            now=DAY + timedelta(days=1),
        )
        _insert_assignment(self.team.pk, "h1", "topic-a")
        _insert_assignment(self.team.pk, "h2", "topic-a", is_outlier=1)
        _insert_assignment(self.team.pk, "h3", "topic-b")
        _insert_assignment(OTHER_TEAM_ID, "h4", "topic-z")

        rebuild_topic_daily(team_id=self.team.pk, window_start=DAY, window_end=DAY + timedelta(days=1))

        assert self._daily() == [
            ("2026-10-19", "query-funnel", "topic-b", 1, 1, 0, 1),
            ("2026-10-19", "query-trends", "", 7, 1, 0, 1),
            ("2026-10-19", "query-trends", "topic-a", 9, 3, 4, 2),
        ]

    def test_latest_assignment_wins_and_rebuild_replaces(self) -> None:
        insert_hourly_calls(self.team.pk, [self._hourly(1, "h1", "query-trends", 3)], now=DAY)
        _insert_assignment(self.team.pk, "h1", "topic-a", timestamp=DAY)
        _insert_assignment(self.team.pk, "h1", "topic-b", timestamp=DAY + timedelta(days=1))

        rebuild_topic_daily(team_id=self.team.pk, window_start=DAY, window_end=DAY + timedelta(days=1))
        rebuild_topic_daily(team_id=self.team.pk, window_start=DAY, window_end=DAY + timedelta(days=1))

        rows = execute_hogql_query(
            query="SELECT topic_id, argMax(calls, inserted_at) FROM mcp_intent_topic_daily GROUP BY topic_id",
            team=self.team,
        ).results
        assert rows == [("topic-b", 3)]
