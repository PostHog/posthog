from datetime import UTC, date, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import (
    DateRange,
    MCPIntentMapBounds,
    MCPIntentMapQuery,
    MCPIntentTopicsQuery,
    MCPSimilarToolsQuery,
    MCPToolIntentProfileQuery,
)

from posthog.clickhouse.client import sync_execute

from products.mcp_analytics.backend.facade.clickhouse_schema import MCP_INTENT_TOPIC_DAILY_WRITABLE_TABLE
from products.mcp_analytics.backend.hogql_queries.intent_topics import (
    MCPIntentMapQueryRunner,
    MCPIntentTopicsQueryRunner,
    MCPSimilarToolsQueryRunner,
    MCPToolIntentProfileQueryRunner,
)
from products.mcp_analytics.backend.models import MCPIntentTopic
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin
from products.mcp_analytics.backend.tests.test_intent_assignments_table import _insert_assignment

OTHER_TEAM_ID = 10**9
TODAY = date(2026, 10, 20)
FROZEN_NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
WINDOW = DateRange(date_from="2026-10-14", date_to="2026-10-20")  # 7 days; previous window = 10-07..10-13


def _daily(
    team_id: int,
    day: date,
    tool: str,
    topic_id: str,
    calls: int,
    sessions: int = 1,
    outlier_calls: int = 0,
    intents: int = 1,
) -> None:
    sync_execute(
        f"INSERT INTO {MCP_INTENT_TOPIC_DAILY_WRITABLE_TABLE} (team_id, day, tool, topic_id, calls, sessions, outlier_calls, intents, inserted_at) VALUES",
        [(team_id, day, tool, topic_id, calls, sessions, outlier_calls, intents, FROZEN_NOW)],
    )


class _Base(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insights = MCPIntentTopic.objects.create(
            team=self.team, label="Create insights", summary="Charts.", centroid=b"", centroid_x=1.0, centroid_y=0.0
        )
        self.flags = MCPIntentTopic.objects.create(
            team=self.team, label="List flags", summary="Flags.", centroid=b"", centroid_x=0.0, centroid_y=1.0
        )
        self.t_insights, self.t_flags = str(self.insights.pk), str(self.flags.pk)


class TestIntentTopicsQuery(_Base):
    def test_ranks_topics_by_calls_with_share_trend_tools_and_coverage(self) -> None:
        _daily(self.team.pk, TODAY, "query-trends", self.t_insights, 60, sessions=5, outlier_calls=3)
        _daily(self.team.pk, TODAY - timedelta(days=1), "query-funnel", self.t_insights, 20, sessions=2)
        _daily(self.team.pk, TODAY, "feature-flag-get-all", self.t_flags, 20)
        _daily(self.team.pk, TODAY, "query-trends", "", 100)  # intents without a topic
        _daily(self.team.pk, TODAY - timedelta(days=8), "query-trends", self.t_insights, 10)  # previous window
        _daily(self.team.pk, TODAY - timedelta(days=8), "feature-flag-get-all", self.t_flags, 30)
        _daily(OTHER_TEAM_ID, TODAY, "query-trends", "other", 999)

        response = MCPIntentTopicsQueryRunner(query=MCPIntentTopicsQuery(dateRange=WINDOW), team=self.team).calculate()

        assert [(t.label, t.calls, t.sessions, t.outlier_calls, t.top_tools) for t in response.results] == [
            ("Create insights", 80, 7, 3, ["query-trends", "query-funnel"]),
            ("List flags", 20, 1, 0, ["feature-flag-get-all"]),
        ]
        insights, flags = response.results
        assert (insights.share_pct, insights.previous_share_pct, insights.trend_pp) == (40.0, 25.0, 15.0)
        assert (flags.share_pct, flags.previous_share_pct, flags.trend_pp) == (10.0, 75.0, -65.0)
        assert (
            response.coverage.calls_with_intent,
            response.coverage.calls_assigned,
            response.coverage.assigned_pct,
        ) == (200, 100, 50.0)

    def test_scopes_to_a_tool_and_limits(self) -> None:
        _daily(self.team.pk, TODAY, "query-trends", self.t_insights, 60)
        _daily(self.team.pk, TODAY, "query-trends", self.t_flags, 5)
        _daily(self.team.pk, TODAY, "feature-flag-get-all", self.t_flags, 20)

        response = MCPIntentTopicsQueryRunner(
            query=MCPIntentTopicsQuery(dateRange=WINDOW, toolName="query-trends", limit=1), team=self.team
        ).calculate()

        assert [(t.label, t.calls, t.share_pct) for t in response.results] == [("Create insights", 60, 92.31)]
        assert response.coverage.calls_with_intent == 65

    def test_no_previous_data_leaves_trend_empty(self) -> None:
        _daily(self.team.pk, TODAY, "query-trends", self.t_insights, 1)

        [topic] = (
            MCPIntentTopicsQueryRunner(query=MCPIntentTopicsQuery(dateRange=WINDOW), team=self.team).calculate().results
        )

        assert (topic.previous_share_pct, topic.trend_pp) == (None, None)


class TestToolIntentProfileQuery(_Base):
    def test_focus_drift_sparkline_and_outliers(self) -> None:
        for offset in range(7):
            _daily(self.team.pk, TODAY - timedelta(days=offset), "query-trends", self.t_insights, 10 + offset)
        _daily(self.team.pk, TODAY, "query-trends", self.t_flags, 6)
        _daily(self.team.pk, TODAY - timedelta(days=9), "query-trends", self.t_flags, 50)  # previous: flags dominated
        _daily(self.team.pk, TODAY - timedelta(days=9), "query-trends", self.t_insights, 10)
        _insert_assignment(
            self.team.pk,
            "o1",
            self.t_insights,
            is_outlier=1,
            distance=0.8,
            intent_text="odd use",
            calls_in_run=4,
            tool="query-trends",
            timestamp=FROZEN_NOW,
        )
        _insert_assignment(self.team.pk, "n1", self.t_insights, is_outlier=0, tool="query-trends", timestamp=FROZEN_NOW)
        _insert_assignment(
            self.team.pk, "o2", self.t_flags, is_outlier=1, tool="feature-flag-get-all", timestamp=FROZEN_NOW
        )

        response = MCPToolIntentProfileQueryRunner(
            query=MCPToolIntentProfileQuery(dateRange=WINDOW, toolName="query-trends"), team=self.team
        ).calculate()

        assert [(t.label, t.calls) for t in response.results] == [("Create insights", 91), ("List flags", 6)]
        assert response.results[0].sparkline == [16, 15, 14, 13, 12, 11, 10]
        assert response.results[1].sparkline == [0, 0, 0, 0, 0, 0, 6]
        assert response.focus.band == "mixed"
        assert 0.5 < response.focus.score < 0.7
        assert [r.label for r in response.drift.growing] == ["Create insights"]
        assert [r.label for r in response.drift.shrinking] == ["List flags"]
        assert response.drift.new == [] and response.drift.gone == []
        assert [(o.intent_hash, o.intent_text, o.calls, o.distance) for o in response.outliers] == [
            ("o1", "odd use", 4, 0.8)
        ]

    def test_single_topic_is_fully_consolidated(self) -> None:
        _daily(self.team.pk, TODAY, "query-trends", self.t_insights, 30)

        response = MCPToolIntentProfileQueryRunner(
            query=MCPToolIntentProfileQuery(dateRange=WINDOW, toolName="query-trends"), team=self.team
        ).calculate()

        assert (response.focus.score, response.focus.band) == (1.0, "consolidated")
        assert [r.label for r in response.drift.new] == ["Create insights"]


class TestSimilarToolsQuery(_Base):
    def test_ranks_tools_by_topic_share_similarity(self) -> None:
        _daily(self.team.pk, TODAY, "query-trends", self.t_insights, 90)
        _daily(self.team.pk, TODAY, "query-trends", self.t_flags, 10)
        _daily(self.team.pk, TODAY, "query-funnel", self.t_insights, 9)
        _daily(self.team.pk, TODAY, "query-funnel", self.t_flags, 1)  # same mix as query-trends
        _daily(self.team.pk, TODAY, "feature-flag-get-all", self.t_flags, 50)  # disjoint-ish
        _daily(self.team.pk, TODAY, "execute-sql", "", 40)  # unassigned only: ignored

        response = MCPSimilarToolsQueryRunner(
            query=MCPSimilarToolsQuery(dateRange=WINDOW, toolName="query-trends"), team=self.team
        ).calculate()

        assert [(t.tool, t.similarity, t.calls, t.shared_topics) for t in response.results] == [
            ("query-funnel", 1.0, 10, ["Create insights", "List flags"]),
            ("feature-flag-get-all", 0.1104, 50, ["List flags"]),
        ]

    def test_unknown_tool_returns_nothing(self) -> None:
        _daily(self.team.pk, TODAY, "query-trends", self.t_insights, 1)

        assert (
            MCPSimilarToolsQueryRunner(query=MCPSimilarToolsQuery(dateRange=WINDOW, toolName="nope"), team=self.team)
            .calculate()
            .results
            == []
        )


class TestIntentMapQuery(_Base):
    def setUp(self) -> None:
        super().setUp()
        _insert_assignment(
            self.team.pk,
            "p1",
            self.t_insights,
            x=1.0,
            y=0.1,
            calls_in_run=9,
            intent_text="plot signups",
            tool="query-trends",
            timestamp=FROZEN_NOW,
        )
        _insert_assignment(
            self.team.pk, "p2", self.t_insights, x=0.9, y=0.0, calls_in_run=5, tool="query-trends", timestamp=FROZEN_NOW
        )
        _insert_assignment(
            self.team.pk,
            "p3",
            self.t_flags,
            x=0.0,
            y=1.0,
            calls_in_run=7,
            tool="feature-flag-get-all",
            timestamp=FROZEN_NOW,
        )
        _insert_assignment(
            self.team.pk, "old", self.t_flags, x=0.0, y=1.0, calls_in_run=70, timestamp=FROZEN_NOW - timedelta(days=30)
        )
        _insert_assignment(OTHER_TEAM_ID, "zz", "other", x=1.0, y=0.0, calls_in_run=99, timestamp=FROZEN_NOW)
        _daily(self.team.pk, TODAY, "query-trends", self.t_insights, 14)
        _daily(self.team.pk, TODAY, "feature-flag-get-all", self.t_flags, 7)

    def test_points_and_topic_bubbles(self) -> None:
        response = MCPIntentMapQueryRunner(query=MCPIntentMapQuery(dateRange=WINDOW), team=self.team).calculate()

        assert [(p.intent_hash, p.calls, p.topic_id, p.is_outlier) for p in response.results] == [
            ("p1", 9, self.t_insights, False),
            ("p3", 7, self.t_flags, False),
            ("p2", 5, self.t_insights, False),
        ]
        assert response.results[0].intent_text == "plot signups"
        assert response.total_points == 3
        assert [(t.label, t.x, t.y, t.calls, t.share_pct) for t in response.topics] == [
            ("Create insights", 1.0, 0.0, 14, 66.67),
            ("List flags", 0.0, 1.0, 7, 33.33),
        ]

    def test_bounds_limit_topic_and_tool_filters(self) -> None:
        bounded = MCPIntentMapQueryRunner(
            query=MCPIntentMapQuery(
                dateRange=WINDOW, bounds=MCPIntentMapBounds(x_min=0.5, x_max=2.0, y_min=-1.0, y_max=1.0), limit=1
            ),
            team=self.team,
        ).calculate()
        assert [p.intent_hash for p in bounded.results] == ["p1"]
        assert bounded.total_points == 2

        by_topic = MCPIntentMapQueryRunner(
            query=MCPIntentMapQuery(dateRange=WINDOW, topicId=self.t_flags), team=self.team
        ).calculate()
        assert [p.intent_hash for p in by_topic.results] == ["p3"]
        assert [t.label for t in by_topic.topics] == ["List flags"]

        by_tool = MCPIntentMapQueryRunner(
            query=MCPIntentMapQuery(dateRange=WINDOW, toolName="query-trends"), team=self.team
        ).calculate()
        assert [p.intent_hash for p in by_tool.results] == ["p1", "p2"]
        assert [t.label for t in by_tool.topics] == ["Create insights"]
