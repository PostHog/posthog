from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError

from posthog.schema import (
    DateRange,
    MCPIntentMapBounds,
    MCPIntentMapQuery,
    MCPIntentTopicsQuery,
    MCPSimilarToolsQuery,
    MCPToolIntentProfileQuery,
)

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.constants import AvailableFeature
from posthog.models import PropertyDefinition
from posthog.models.organization import OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.mcp_analytics.backend.facade.clickhouse_schema import MCP_INTENT_TOPIC_DAILY_WRITABLE_TABLE
from products.mcp_analytics.backend.hogql_queries.intent_topics import (
    MCPIntentMapQueryRunner,
    MCPIntentTopicsQueryRunner,
    MCPSimilarToolsQueryRunner,
    MCPToolIntentProfileQueryRunner,
)
from products.mcp_analytics.backend.intent_topics.corpus import HourlyCalls
from products.mcp_analytics.backend.intent_topics.rollups import insert_hourly_calls
from products.mcp_analytics.backend.models import MCPIntentClusteringRun, MCPIntentTopic
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin
from products.mcp_analytics.backend.tests.intent_topics_helpers import recent_hour
from products.mcp_analytics.backend.tests.test_intent_assignments_table import _insert_assignment

OTHER_TEAM_ID = 10**9
NOW = recent_hour(days_ago=0)
TODAY = NOW.date() - timedelta(days=1)
# 7 days; the previous window is the 7 days before it.
WINDOW = DateRange(date_from=(TODAY - timedelta(days=6)).isoformat(), date_to=TODAY.isoformat())


def _daily(
    team_id: int,
    day: date,
    tool: str,
    topic_id: str,
    calls: int,
    conversations: tuple[int, ...] = (1,),
    outlier_calls: int = 0,
    intents: int = 1,
) -> None:
    sync_execute(
        f"INSERT INTO {MCP_INTENT_TOPIC_DAILY_WRITABLE_TABLE} (team_id, day, tool, topic_id, calls, conversation_hashes, outlier_calls, intents, inserted_at) VALUES",
        [(team_id, day, tool, topic_id, calls, list(conversations), outlier_calls, intents, NOW)],
    )


def _hourly(team_id: int, day: date, intent_hash: str, tool: str, calls: int) -> None:
    hour = datetime.combine(day, time(12), tzinfo=UTC)
    insert_hourly_calls(
        team_id, [HourlyCalls(hour=hour, hash=intent_hash, tool=tool, calls=calls, conversations=(1,))], now=NOW
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
        _daily(self.team.pk, TODAY, "query-trends", self.t_insights, 60, conversations=(1, 2, 3, 4, 5), outlier_calls=3)
        _daily(self.team.pk, TODAY - timedelta(days=1), "query-funnel", self.t_insights, 20, conversations=(5, 6))
        _daily(self.team.pk, TODAY, "feature-flag-get-all", self.t_flags, 20)
        _daily(self.team.pk, TODAY, "query-trends", "", 100)  # intents without a topic
        _daily(self.team.pk, TODAY - timedelta(days=8), "query-trends", self.t_insights, 10)  # previous window
        _daily(self.team.pk, TODAY - timedelta(days=8), "feature-flag-get-all", self.t_flags, 30)
        _daily(self.team.pk, TODAY - timedelta(days=14), "feature-flag-get-all", self.t_flags, 1000)  # before both
        _daily(OTHER_TEAM_ID, TODAY, "query-trends", "other", 999)

        response = MCPIntentTopicsQueryRunner(query=MCPIntentTopicsQuery(dateRange=WINDOW), team=self.team).calculate()

        assert [(t.label, t.calls, t.sessions, t.outlier_calls, t.top_tools) for t in response.results] == [
            ("Create insights", 80, 6, 3, ["query-trends", "query-funnel"]),
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

    def test_a_child_environment_reads_its_project_topic_labels(self) -> None:
        child = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="Child"
        )
        _daily(child.pk, TODAY, "query-trends", self.t_insights, 5)

        response = MCPIntentTopicsQueryRunner(query=MCPIntentTopicsQuery(dateRange=WINDOW), team=child).calculate()

        assert [(t.label, t.calls) for t in response.results] == [("Create insights", 5)]

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
        # o1 was assigned weeks ago and is still called in the window.
        _insert_assignment(
            self.team.pk,
            "o1",
            self.t_insights,
            is_outlier=1,
            distance=0.8,
            intent_text="odd use",
            timestamp=NOW - timedelta(days=20),
        )
        _hourly(self.team.pk, TODAY, "o1", "query-trends", 4)
        _insert_assignment(self.team.pk, "n1", self.t_insights, is_outlier=0, timestamp=NOW)
        _hourly(self.team.pk, TODAY, "n1", "query-trends", 9)
        _insert_assignment(self.team.pk, "o2", self.t_flags, is_outlier=1, timestamp=NOW)
        _hourly(self.team.pk, TODAY, "o2", "feature-flag-get-all", 9)
        # o3 was assigned in the window but nobody called it there.
        _insert_assignment(self.team.pk, "o3", self.t_flags, is_outlier=1, timestamp=NOW)
        _hourly(self.team.pk, TODAY - timedelta(days=20), "o3", "query-trends", 9)

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
        assert [(o.intent_hash, o.intent_text, o.calls, o.distance, o.tool) for o in response.outliers] == [
            ("o1", "odd use", 4, 0.8, "query-trends")
        ]

    def test_sparklines_cover_every_day_of_a_long_window(self) -> None:
        topics = [f"topic-{i}" for i in range(5)]
        for offset in range(30):
            for topic in topics:
                _daily(self.team.pk, TODAY - timedelta(days=offset), "query-trends", topic, 1)

        response = MCPToolIntentProfileQueryRunner(
            query=MCPToolIntentProfileQuery(
                dateRange=DateRange(date_from=(TODAY - timedelta(days=29)).isoformat(), date_to=TODAY.isoformat()),
                toolName="query-trends",
            ),
            team=self.team,
        ).calculate()

        assert [(t.topic_id, t.calls, t.sparkline) for t in response.results] == [
            (topic, 30, [1] * 30) for topic in topics
        ]

    def test_single_topic_is_fully_consolidated_and_drift_shares_count_unassigned_calls(self) -> None:
        _daily(self.team.pk, TODAY, "query-trends", self.t_insights, 30)
        _daily(self.team.pk, TODAY, "query-trends", "", 30)

        response = MCPToolIntentProfileQueryRunner(
            query=MCPToolIntentProfileQuery(dateRange=WINDOW, toolName="query-trends"), team=self.team
        ).calculate()

        assert (response.focus.score, response.focus.band) == (1.0, "consolidated")
        assert [(r.label, r.share_pct) for r in response.drift.new] == [("Create insights", 50.0)]
        assert [(t.label, t.share_pct) for t in response.results] == [("Create insights", 50.0)]


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
        _insert_assignment(self.team.pk, "p1", self.t_insights, x=1.0, y=0.1, intent_text="plot signups", timestamp=NOW)
        # p2 moved from insights to flags: its older assignment must not resurface under a filter.
        _insert_assignment(self.team.pk, "p2", self.t_insights, x=0.9, y=0.0, timestamp=NOW - timedelta(days=2))
        _insert_assignment(self.team.pk, "p2", self.t_flags, x=0.1, y=0.9, timestamp=NOW)
        # p3 was assigned before the window and is still called in it.
        _insert_assignment(self.team.pk, "p3", self.t_flags, x=0.0, y=1.0, timestamp=NOW - timedelta(days=20))
        _insert_assignment(self.team.pk, "idle", self.t_flags, x=0.0, y=1.0, timestamp=NOW)
        _insert_assignment(OTHER_TEAM_ID, "zz", "other", x=1.0, y=0.0, timestamp=NOW)
        _hourly(self.team.pk, TODAY, "p1", "query-trends", 9)
        _hourly(self.team.pk, TODAY, "p1", "query-funnel", 1)
        _hourly(self.team.pk, TODAY, "p2", "query-trends", 5)
        _hourly(self.team.pk, TODAY, "p3", "feature-flag-get-all", 7)
        _hourly(self.team.pk, TODAY - timedelta(days=20), "idle", "feature-flag-get-all", 70)
        _hourly(OTHER_TEAM_ID, TODAY, "zz", "query-trends", 99)
        _daily(self.team.pk, TODAY, "query-trends", self.t_insights, 14)
        _daily(self.team.pk, TODAY, "feature-flag-get-all", self.t_flags, 7)
        _daily(self.team.pk, TODAY, "query-trends", "", 7)

    def test_points_and_topic_bubbles(self) -> None:
        # Archived after the window: its calls in the window still need a bubble.
        MCPIntentTopic.objects.filter(pk=self.flags.pk).update(status=MCPIntentTopic.Status.ARCHIVED)

        response = MCPIntentMapQueryRunner(query=MCPIntentMapQuery(dateRange=WINDOW), team=self.team).calculate()

        assert [(p.intent_hash, p.calls, p.topic_id, p.tool) for p in response.results] == [
            ("p1", 10, self.t_insights, "query-trends"),
            ("p3", 7, self.t_flags, "feature-flag-get-all"),
            ("p2", 5, self.t_flags, "query-trends"),
        ]
        assert response.results[0].intent_text == "plot signups"
        assert response.total_points == 3
        assert [(t.label, t.x, t.y, t.calls, t.share_pct) for t in response.topics] == [
            ("Create insights", 1.0, 0.0, 14, 50.0),
            ("List flags", 0.0, 1.0, 7, 25.0),
        ]

    def test_bounds_limit_topic_and_tool_filters(self) -> None:
        bounded = MCPIntentMapQueryRunner(
            query=MCPIntentMapQuery(
                dateRange=WINDOW, bounds=MCPIntentMapBounds(x_min=0.5, x_max=2.0, y_min=-1.0, y_max=1.0), limit=1
            ),
            team=self.team,
        ).calculate()
        assert [p.intent_hash for p in bounded.results] == ["p1"]
        assert bounded.total_points == 1

        by_topic = MCPIntentMapQueryRunner(
            query=MCPIntentMapQuery(dateRange=WINDOW, topicId=self.t_insights), team=self.team
        ).calculate()
        assert [p.intent_hash for p in by_topic.results] == ["p1"]
        assert by_topic.total_points == 1
        assert [t.label for t in by_topic.topics] == ["Create insights"]

        by_tool = MCPIntentMapQueryRunner(
            query=MCPIntentMapQuery(dateRange=WINDOW, toolName="query-trends"), team=self.team
        ).calculate()
        assert [(p.intent_hash, p.calls) for p in by_tool.results] == [("p1", 9), ("p2", 5)]
        assert [t.label for t in by_tool.topics] == ["Create insights"]

    def test_points_assigned_before_the_latest_refit_use_an_older_basis_and_stay_off_the_map(self) -> None:
        refit = MCPIntentClusteringRun.objects.create(
            team=self.team, run_id="refit-1", kind="refit", status=MCPIntentClusteringRun.Status.SUCCEEDED
        )
        MCPIntentClusteringRun.objects.filter(pk=refit.pk).update(started_at=NOW - timedelta(days=10))

        response = MCPIntentMapQueryRunner(query=MCPIntentMapQuery(dateRange=WINDOW), team=self.team).calculate()

        assert [p.intent_hash for p in response.results] == ["p1", "p2"]
        assert response.total_points == 2


class TestIntentTopicsAccess(_Base):
    def _restrict(self, property_name: str) -> None:
        self.organization.available_product_features = [
            {"name": AvailableFeature.PROPERTY_ACCESS_CONTROL, "key": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name=property_name, property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(
            team=self.team, property_definition=definition, access_level=PropertyAccessLevel.NONE.value
        )

    def test_a_member_denied_the_intent_property_sees_no_intent_text_hashes_or_labels(self) -> None:
        _daily(self.team.pk, TODAY, "query-trends", self.t_insights, 10)
        _insert_assignment(self.team.pk, "o1", self.t_insights, is_outlier=1, intent_text="odd use", timestamp=NOW)
        _hourly(self.team.pk, TODAY, "o1", "query-trends", 4)
        self.insights.summary = "Agents chart weekly signups."
        self.insights.save()
        self._restrict("$mcp_intent")

        profile = MCPToolIntentProfileQueryRunner(
            query=MCPToolIntentProfileQuery(dateRange=WINDOW, toolName="query-trends"), team=self.team, user=self.user
        ).calculate()
        hourly_hashes = execute_hogql_query(
            query="SELECT intent_hash FROM posthog.mcp_intent_calls_hourly", team=self.team, user=self.user
        ).results

        assert profile.outliers == []
        assert [(t.label, t.summary) for t in profile.results] == [(f"Topic {self.t_insights[:8]}", "")]
        assert hourly_hashes == [(None,)]

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        admin_profile = MCPToolIntentProfileQueryRunner(
            query=MCPToolIntentProfileQuery(dateRange=WINDOW, toolName="query-trends"), team=self.team, user=self.user
        ).calculate()
        assert [o.intent_text for o in admin_profile.outliers] == ["odd use"]
        assert [t.label for t in admin_profile.results] == ["Create insights"]

    @parameterized.expand([("$mcp_session_id",), ("$session_id",)])
    def test_a_member_denied_a_session_id_property_sees_no_conversation_hashes(self, property_name: str) -> None:
        _daily(self.team.pk, TODAY, "query-trends", self.t_insights, 10, conversations=(11, 12))
        _hourly(self.team.pk, TODAY, "o1", "query-trends", 4)
        self._restrict(property_name)

        def run(query: str) -> list[tuple]:
            return execute_hogql_query(query=query, team=self.team, user=self.user).results

        topics = MCPIntentTopicsQueryRunner(
            query=MCPIntentTopicsQuery(dateRange=WINDOW), team=self.team, user=self.user
        ).calculate()

        assert run("SELECT conversation_hashes FROM posthog.mcp_intent_calls_hourly") == [([],)]
        assert run("SELECT conversation_hashes FROM posthog.mcp_intent_topic_daily") == [([],)]
        assert run("SELECT count() FROM posthog.mcp_intent_topic_daily WHERE has(conversation_hashes, 11)") == [(0,)]
        assert [(t.calls, t.sessions) for t in topics.results] == [(10, 0)]

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        admin_topics = MCPIntentTopicsQueryRunner(
            query=MCPIntentTopicsQuery(dateRange=WINDOW), team=self.team, user=self.user
        ).calculate()
        assert run("SELECT conversation_hashes FROM posthog.mcp_intent_topic_daily") == [([11, 12],)]
        assert [(t.calls, t.sessions) for t in admin_topics.results] == [(10, 2)]

    @parameterized.expand([("$mcp_tool_name",), ("$mcp_exec_tool_call_name",), ("$mcp_exec_target_tool",)])
    def test_a_member_denied_a_tool_property_sees_no_tool_names(self, property_name: str) -> None:
        _daily(self.team.pk, TODAY, "query-trends", self.t_insights, 10)
        _hourly(self.team.pk, TODAY, "o1", "query-trends", 4)
        self._restrict(property_name)

        def run(query: str) -> list[tuple]:
            return execute_hogql_query(query=query, team=self.team, user=self.user).results

        assert run("SELECT tool FROM posthog.mcp_intent_calls_hourly") == [(None,)]
        assert run("SELECT tool FROM posthog.mcp_intent_topic_daily") == [(None,)]
        assert run("SELECT count() FROM posthog.mcp_intent_topic_daily WHERE tool = 'query-trends'") == [(0,)]

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        assert run("SELECT tool FROM posthog.mcp_intent_topic_daily") == [("query-trends",)]

    @parameterized.expand(
        [
            (kind, scopes, expected_status)
            for kind in (
                "MCPIntentTopicsQuery",
                "MCPToolIntentProfileQuery",
                "MCPSimilarToolsQuery",
                "MCPIntentMapQuery",
            )
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
            {"query": {"kind": kind, "toolName": "query-trends"}},
            HTTP_AUTHORIZATION=f"Bearer {value}",
        )

        assert response.status_code == expected_status, response.json()


class TestIntentTopicQueryLimits(SimpleTestCase):
    @parameterized.expand(
        [
            ("topics", lambda limit: MCPIntentTopicsQuery(limit=limit)),
            ("profile", lambda limit: MCPToolIntentProfileQuery(limit=limit, toolName="query-trends")),
            ("similar", lambda limit: MCPSimilarToolsQuery(limit=limit, toolName="query-trends")),
            ("map", lambda limit: MCPIntentMapQuery(limit=limit)),
        ]
    )
    def test_rejects_limits_below_one(self, _name: str, build: Callable[[int], object]) -> None:
        for limit in (0, -1):
            with self.assertRaises(ValidationError):
                build(limit)
