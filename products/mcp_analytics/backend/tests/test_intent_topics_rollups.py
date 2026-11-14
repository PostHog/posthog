from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import DateRange, MCPIntentTopicsQuery

from posthog.hogql.query import execute_hogql_query

from products.mcp_analytics.backend.hogql_queries.intent_topics import MCPIntentTopicsQueryRunner
from products.mcp_analytics.backend.intent_hash import intent_hash
from products.mcp_analytics.backend.intent_topics.corpus import HourlyCalls, fetch_hourly_calls
from products.mcp_analytics.backend.intent_topics.rollups import insert_hourly_calls, rebuild_topic_daily
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin
from products.mcp_analytics.backend.tests.intent_topics_helpers import recent_hour
from products.mcp_analytics.backend.tests.test_intent_assignments_table import _insert_assignment

OTHER_TEAM_ID = 10**9
DAY = recent_hour(days_ago=3).replace(hour=0)


class TestFetchHourlyCalls(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand([("utc", "UTC"), ("fractional_offset", "Asia/Kolkata")])
    def test_returns_complete_utc_hours_by_intent_and_tool_with_distinct_conversations(
        self, _name: str, timezone: str
    ) -> None:
        self.team.timezone = timezone
        self.team.save()
        for minute, session in ((5, "s1"), (10, "s1"), (50, "s2"), (70, "s2"), (130, "s3")):
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

        # The window starts and ends inside an hour: the first hour is read whole, the last one is left
        # for the next run, so a later run never replaces a complete bucket with a partial one.
        for page_size in (1, 50_000):
            rows = fetch_hourly_calls(
                self.team, since=DAY + timedelta(minutes=45), until=DAY + timedelta(minutes=150), page_size=page_size
            )

            assert [
                ((r.hour.astimezone(UTC) - DAY).total_seconds() / 3600, r.hash, r.tool, r.calls, len(r.conversations))
                for r in rows
            ] == [
                (0.0, intent_hash("plot signups"), "query-funnel", 1, 1),
                (0.0, intent_hash("plot signups"), "query-trends", 3, 2),
                (1.0, intent_hash("plot signups"), "query-trends", 1, 1),
            ]


class TestRebuildTopicDaily(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _hourly(
        self, hour: int, hash_: str, tool: str, calls: int, conversations: tuple[int, ...] = (1,)
    ) -> HourlyCalls:
        return HourlyCalls(
            hour=DAY + timedelta(hours=hour), hash=hash_, tool=tool, calls=calls, conversations=conversations
        )

    def _daily(self) -> list[tuple]:
        return execute_hogql_query(
            query="""
                SELECT toString(day), tool, topic_id, calls, length(conversation_hashes), outlier_calls, intents
                FROM posthog.mcp_intent_topic_daily
                ORDER BY tool, topic_id, inserted_at
            """,
            team=self.team,
        ).results

    def _topic_calls(self) -> list[tuple]:
        response = MCPIntentTopicsQueryRunner(
            query=MCPIntentTopicsQuery(
                dateRange=DateRange(date_from=DAY.date().isoformat(), date_to=DAY.date().isoformat())
            ),
            team=self.team,
        ).calculate()
        return [(t.topic_id, t.calls, t.sessions) for t in response.results]

    def test_sums_calls_per_tool_and_topic_with_unassigned_outliers_and_distinct_conversations(self) -> None:
        insert_hourly_calls(
            self.team.pk,
            [
                self._hourly(1, "h1", "query-trends", 3, conversations=(1,)),
                self._hourly(2, "h1", "query-trends", 2, conversations=(1,)),
                self._hourly(1, "h2", "query-trends", 4, conversations=(1, 2)),
                self._hourly(1, "h3", "query-funnel", 1),
                self._hourly(1, "h4", "query-trends", 7),
            ],
            now=DAY + timedelta(days=1),
        )
        _insert_assignment(self.team.pk, "h1", "topic-a")
        _insert_assignment(self.team.pk, "h2", "topic-a", is_outlier=1)
        _insert_assignment(self.team.pk, "h3", "topic-b")
        _insert_assignment(OTHER_TEAM_ID, "h4", "topic-z")

        rebuild_topic_daily(
            team_id=self.team.pk, window_start=DAY, window_end=DAY + timedelta(days=1), now=DAY + timedelta(days=1)
        )

        assert self._daily() == [
            (DAY.date().isoformat(), "query-funnel", "topic-b", 1, 1, 0, 1),
            (DAY.date().isoformat(), "query-trends", "", 7, 1, 0, 1),
            (DAY.date().isoformat(), "query-trends", "topic-a", 9, 2, 4, 2),
        ]

    def test_reads_the_latest_hourly_version_and_rebuilds_whole_days(self) -> None:
        insert_hourly_calls(self.team.pk, [self._hourly(1, "h1", "query-trends", 3)], now=DAY + timedelta(hours=2))
        # A later sync re-reads the same complete hour after late events arrive.
        insert_hourly_calls(self.team.pk, [self._hourly(1, "h1", "query-trends", 5)], now=DAY + timedelta(hours=3))
        insert_hourly_calls(self.team.pk, [self._hourly(23, "h1", "query-trends", 1)], now=DAY + timedelta(hours=24))
        _insert_assignment(self.team.pk, "h1", "topic-a")

        rebuild_topic_daily(
            team_id=self.team.pk, window_start=DAY, window_end=DAY + timedelta(days=1), now=DAY + timedelta(days=1)
        )
        # The next nightly window overlaps only the last two hours of the day.
        rebuild_topic_daily(
            team_id=self.team.pk,
            window_start=DAY + timedelta(hours=22),
            window_end=DAY + timedelta(hours=48),
            now=DAY + timedelta(days=2),
        )

        assert self._topic_calls() == [("topic-a", 6, 1)]

    def test_reassigned_calls_move_between_topics_without_double_counting(self) -> None:
        insert_hourly_calls(self.team.pk, [self._hourly(1, "h1", "query-trends", 3)], now=DAY)
        _insert_assignment(self.team.pk, "h1", "topic-a", timestamp=DAY)
        rebuild_topic_daily(
            team_id=self.team.pk, window_start=DAY, window_end=DAY + timedelta(days=1), now=DAY + timedelta(hours=1)
        )
        _insert_assignment(self.team.pk, "h1", "topic-b", timestamp=DAY + timedelta(days=1))

        # A second rebuild inside the same second, as a refit followed by its reassignment can do.
        rebuild_topic_daily(
            team_id=self.team.pk,
            window_start=DAY,
            window_end=DAY + timedelta(days=1),
            now=DAY + timedelta(hours=1, microseconds=500),
        )

        assert self._topic_calls() == [("topic-b", 3, 1)]

    def test_days_follow_the_project_timezone(self) -> None:
        self.team.timezone = "Europe/Berlin"
        self.team.save()
        late_utc_hour = DAY + timedelta(hours=23)
        local_day = late_utc_hour.astimezone(ZoneInfo("Europe/Berlin")).date()
        insert_hourly_calls(self.team.pk, [self._hourly(23, "h1", "query-trends", 4)], now=DAY + timedelta(days=1))
        _insert_assignment(self.team.pk, "h1", "topic-a")

        rebuild_topic_daily(
            team_id=self.team.pk,
            window_start=DAY,
            window_end=DAY + timedelta(days=2),
            now=DAY + timedelta(days=2),
            timezone=self.team.timezone,
        )

        def topic_calls(day: str) -> list[tuple]:
            response = MCPIntentTopicsQueryRunner(
                query=MCPIntentTopicsQuery(dateRange=DateRange(date_from=day, date_to=day)), team=self.team
            ).calculate()
            return [(t.topic_id, t.calls) for t in response.results]

        assert local_day != DAY.date()
        assert topic_calls(local_day.isoformat()) == [("topic-a", 4)]
        assert topic_calls(DAY.date().isoformat()) == []
