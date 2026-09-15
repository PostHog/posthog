from collections.abc import Callable
from datetime import timedelta

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.schema import (
    CacheMissResponse,
    QueryStatus,
    QueryStatusResponse,
    WebGoalsQueryResponse,
    WebOverviewQueryResponse,
    WebStatsTableQueryResponse,
)

from posthog.models import Team
from posthog.models.utils import uuid7

from products.actions.backend.models.action import Action
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_tools.backend.models.join import DataWarehouseJoin
from products.web_analytics.backend.hogql_queries.web_goals import NoActionsError
from products.web_analytics.backend.weekly_digest import (
    _default_overview,
    _format_duration,
    auto_select_project_for_user,
    build_team_digest,
    get_goals_for_team,
    get_overview_for_team,
    get_top_pages,
    get_top_sources,
)

QUERY_TIMESTAMP = "2025-01-29"

DIGEST_QUERY_CASES = [
    (get_overview_for_team, "WebOverviewQueryRunner", WebOverviewQueryResponse, _default_overview()),
    (get_top_pages, "WebStatsTableQueryRunner", WebStatsTableQueryResponse, []),
    (get_top_sources, "WebStatsTableQueryRunner", WebStatsTableQueryResponse, []),
    (get_goals_for_team, "WebGoalsQueryRunner", WebGoalsQueryResponse, []),
]


class TestDigestQueryFailures(SimpleTestCase):
    @parameterized.expand(DIGEST_QUERY_CASES)
    def test_query_exceptions_are_not_zero_traffic(
        self, query: Callable[..., object], runner_name: str, *_: object
    ) -> None:
        with patch(f"products.web_analytics.backend.weekly_digest.{runner_name}") as runner:
            runner.return_value.run.side_effect = TimeoutError("Query timed out")
            with self.assertRaises(TimeoutError):
                query(Team(pk=1))

    @parameterized.expand(DIGEST_QUERY_CASES)
    def test_empty_results_are_distinct_from_failed_or_missing_results(
        self, query: Callable[..., object], runner_name: str, response_type: type, expected_empty: object
    ) -> None:
        with patch(f"products.web_analytics.backend.weekly_digest.{runner_name}") as runner:
            for response in [
                CacheMissResponse(),
                QueryStatusResponse(query_status=QueryStatus(id="pending-query", team_id=1, complete=False)),
                response_type(results=[], error="Query failed"),
            ]:
                with self.subTest(response=type(response).__name__):
                    runner.return_value.run.return_value = response
                    with self.assertRaises(ValueError):
                        query(Team(pk=1))

            runner.return_value.run.return_value = response_type(results=[])
            assert query(Team(pk=1)) == expected_empty

    def test_no_configured_actions_is_a_valid_empty_goals_section(self) -> None:
        with patch("products.web_analytics.backend.weekly_digest.WebGoalsQueryRunner") as runner:
            runner.return_value.run.side_effect = NoActionsError()
            assert get_goals_for_team(Team(pk=1)) == []

    def test_an_incomplete_section_stops_digest_construction(self) -> None:
        with (
            patch("products.web_analytics.backend.weekly_digest.get_overview_for_team", return_value={}),
            patch("products.web_analytics.backend.weekly_digest.get_top_pages", side_effect=TimeoutError),
        ):
            with self.assertRaises(TimeoutError):
                build_team_digest(Team(pk=1))


def _create_pageview(
    team,
    distinct_id="user_1",
    session_id=None,
    url=None,
    referring_domain=None,
    timestamp=None,
):
    props: dict = {"$session_id": session_id or str(uuid7(timestamp or "2025-01-25"))}
    if url:
        props["$current_url"] = url
        props["$pathname"] = url.split("//")[-1].split("/", 1)[-1] if "//" in url else url
    if referring_domain:
        props["$referring_domain"] = referring_domain
    _create_event(
        team=team,
        event="$pageview",
        distinct_id=distinct_id,
        timestamp=timestamp or (timezone.now() - timedelta(days=1)).isoformat(),
        properties=props,
    )


class TestFormatDuration:
    @parameterized.expand(
        [
            (None, "0s"),
            (0, "0s"),
            (-5, "0s"),
            (45, "45s"),
            (60, "1m"),
            (120, "2m"),
            (154, "2m 34s"),
        ]
    )
    def test_format_duration(self, seconds, expected):
        assert _format_duration(seconds) == expected


class TestAutoSelectProjectForUser(ClickhouseTestMixin, APIBaseTest):
    def test_picks_team_with_most_visitors(self):
        team_b = Team.objects.create(organization=self.organization, name="Team B")

        team_traffic_data = {
            self.team.pk: {"visitors": {"current": 10}, "team": self.team},
            team_b.pk: {"visitors": {"current": 50}, "team": team_b},
        }

        result = auto_select_project_for_user(self.user, team_traffic_data)
        assert result is True

        self.user.refresh_from_db()
        project_enabled = self.user.notification_settings.get("web_analytics_weekly_digest_project_enabled", {})
        assert project_enabled[str(team_b.pk)] is True
        assert str(self.team.pk) not in project_enabled

    def test_skips_if_already_configured(self):
        self.user.partial_notification_settings = {
            "web_analytics_weekly_digest_project_enabled": {str(self.team.pk): True},
        }
        self.user.save()

        team_traffic_data = {
            self.team.pk: {"visitors": {"current": 10}, "team": self.team},
        }

        result = auto_select_project_for_user(self.user, team_traffic_data)
        assert result is False

        self.user.refresh_from_db()
        assert self.user.notification_settings["web_analytics_weekly_digest_project_enabled"] == {
            str(self.team.pk): True
        }

    def test_noop_when_no_teams(self):
        result = auto_select_project_for_user(self.user, {})
        assert result is False

        self.user.refresh_from_db()
        assert "web_analytics_weekly_digest_project_enabled" not in (self.user.partial_notification_settings or {})


class TestGetOverviewForTeam(ClickhouseTestMixin, APIBaseTest):
    def test_returns_overview_with_events(self):
        session_id = str(uuid7("2025-01-25"))
        with time_machine.travel(QUERY_TIMESTAMP, tick=False):
            _create_person(team_id=self.team.pk, distinct_ids=["user_1"])
            for _ in range(3):
                _create_pageview(self.team, distinct_id="user_1", session_id=session_id, timestamp="2025-01-25")
            flush_persons_and_events()

            result = get_overview_for_team(self.team)

        assert "visitors" in result
        assert result["visitors"]["current"] > 0
        assert "pageviews" in result
        assert result["pageviews"]["current"] >= 3
        assert "sessions" in result
        assert "bounce_rate" in result
        assert "avg_session_duration" in result

    def test_returns_zero_values_for_team_with_no_events(self):
        with time_machine.travel(QUERY_TIMESTAMP, tick=False):
            result = get_overview_for_team(self.team)

        assert result == {
            "visitors": {"current": 0, "previous": None, "change": None},
            "pageviews": {"current": 0, "previous": None, "change": None},
            "sessions": {"current": 0, "previous": None, "change": None},
            "bounce_rate": {"current": 0.0, "previous": None, "change": None},
            "avg_session_duration": {"current": "0s", "previous": "0s", "change": None},
        }


class TestGetTopPages(ClickhouseTestMixin, APIBaseTest):
    def test_returns_pages_ordered_by_visitors(self):
        with time_machine.travel(QUERY_TIMESTAMP, tick=False):
            _create_person(team_id=self.team.pk, distinct_ids=["user_1"])
            _create_person(team_id=self.team.pk, distinct_ids=["user_2"])
            _create_person(team_id=self.team.pk, distinct_ids=["user_3"])
            session1, session2, session3 = str(uuid7("2025-01-25")), str(uuid7("2025-01-25")), str(uuid7("2025-01-25"))
            _create_pageview(
                self.team,
                distinct_id="user_1",
                session_id=session1,
                url="https://example.com/popular",
                timestamp="2025-01-25",
            )
            _create_pageview(
                self.team,
                distinct_id="user_2",
                session_id=session2,
                url="https://example.com/popular",
                timestamp="2025-01-25",
            )
            _create_pageview(
                self.team,
                distinct_id="user_3",
                session_id=session3,
                url="https://example.com/popular",
                timestamp="2025-01-25",
            )
            _create_pageview(
                self.team,
                distinct_id="user_1",
                session_id=session1,
                url="https://example.com/less-popular",
                timestamp="2025-01-25",
            )
            flush_persons_and_events()

            result = get_top_pages(self.team)

        assert len(result) >= 2
        assert result[0]["visitors"] >= result[-1]["visitors"]
        assert "path" in result[0]
        assert "change" in result[0]
        assert result[0]["change"] is None

    def test_includes_week_over_week_change(self):
        with time_machine.travel(QUERY_TIMESTAMP, tick=False):
            _create_person(team_id=self.team.pk, distinct_ids=["prev_user"])
            _create_pageview(
                self.team,
                distinct_id="prev_user",
                session_id=str(uuid7("2025-01-18")),
                url="https://example.com/pricing",
                timestamp="2025-01-18",
            )
            for i in range(3):
                distinct_id = f"curr_user_{i}"
                _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
                _create_pageview(
                    self.team,
                    distinct_id=distinct_id,
                    session_id=str(uuid7("2025-01-25")),
                    url="https://example.com/pricing",
                    timestamp="2025-01-25",
                )
            flush_persons_and_events()

            result = get_top_pages(self.team)

        assert len(result) == 1
        assert result[0]["visitors"] == 3
        change = result[0]["change"]
        assert change is not None
        assert change["direction"] == "Up"
        assert change["text"].startswith("Up")

    def test_respects_limit(self):
        with time_machine.travel(QUERY_TIMESTAMP, tick=False):
            _create_person(team_id=self.team.pk, distinct_ids=["user_1"])
            session = str(uuid7("2025-01-25"))
            for i in range(5):
                _create_pageview(
                    self.team,
                    distinct_id="user_1",
                    session_id=session,
                    url=f"https://example.com/page-{i}",
                    timestamp="2025-01-25",
                )
            flush_persons_and_events()

            result = get_top_pages(self.team, limit=2)

        assert len(result) <= 2

    def test_returns_empty_for_no_events(self):
        with time_machine.travel(QUERY_TIMESTAMP, tick=False):
            result = get_top_pages(self.team)
        assert result == []


class TestGetTopSources(ClickhouseTestMixin, APIBaseTest):
    def test_returns_sources_with_visitors(self):
        with time_machine.travel(QUERY_TIMESTAMP, tick=False):
            _create_person(team_id=self.team.pk, distinct_ids=["user_1"])
            session = str(uuid7("2025-01-25"))
            _create_pageview(
                self.team,
                distinct_id="user_1",
                session_id=session,
                referring_domain="google.com",
                url="https://example.com/",
                timestamp="2025-01-25",
            )
            flush_persons_and_events()

            result = get_top_sources(self.team)

        sources = [r["name"] for r in result]
        assert sources == ["google.com"]
        assert all(r["visitors"] > 0 for r in result)
        assert "change" in result[0]
        assert result[0]["change"] is None

    def test_includes_week_over_week_change(self):
        with time_machine.travel(QUERY_TIMESTAMP, tick=False):
            _create_person(team_id=self.team.pk, distinct_ids=["prev_user"])
            _create_pageview(
                self.team,
                distinct_id="prev_user",
                session_id=str(uuid7("2025-01-18")),
                referring_domain="google.com",
                url="https://example.com/",
                timestamp="2025-01-18",
            )
            for i in range(3):
                distinct_id = f"curr_user_{i}"
                _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
                _create_pageview(
                    self.team,
                    distinct_id=distinct_id,
                    session_id=str(uuid7("2025-01-25")),
                    referring_domain="google.com",
                    url="https://example.com/",
                    timestamp="2025-01-25",
                )
            flush_persons_and_events()

            result = get_top_sources(self.team)

        google = next(r for r in result if r["name"] == "google.com")
        assert google["visitors"] == 3
        change = google["change"]
        assert change is not None
        assert change["direction"] == "Up"
        assert change["text"].startswith("Up")

    def test_filters_out_empty_sources(self):
        with time_machine.travel(QUERY_TIMESTAMP, tick=False):
            _create_person(team_id=self.team.pk, distinct_ids=["user_1"])
            session = str(uuid7("2025-01-25"))
            _create_pageview(
                self.team,
                distinct_id="user_1",
                session_id=session,
                url="https://example.com/",
                timestamp="2025-01-25",
            )
            flush_persons_and_events()

            result = get_top_sources(self.team)

        assert all(r["name"] != "" for r in result)

    def test_returns_empty_for_no_events(self):
        with time_machine.travel(QUERY_TIMESTAMP, tick=False):
            result = get_top_sources(self.team)
        assert result == []


class TestGetGoalsForTeam(ClickhouseTestMixin, APIBaseTest):
    def test_returns_empty_when_no_actions(self):
        with time_machine.travel(QUERY_TIMESTAMP, tick=False):
            result = get_goals_for_team(self.team)
        assert result == []

    def test_returns_goals_with_conversions(self):
        with time_machine.travel(QUERY_TIMESTAMP, tick=False):
            Action.objects.create(
                team=self.team,
                name="Signed Up",
                steps_json=[{"event": "signed_up"}],
                last_calculated_at=timezone.now(),
            )
            _create_person(team_id=self.team.pk, distinct_ids=["user_1"])
            session = str(uuid7("2025-01-25"))
            _create_pageview(self.team, distinct_id="user_1", session_id=session, timestamp="2025-01-25")
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="user_1",
                timestamp="2025-01-25",
                properties={"$session_id": session},
            )
            flush_persons_and_events()

            result = get_goals_for_team(self.team)

        assert len(result) >= 1
        goal = next(g for g in result if g["name"] == "Signed Up")
        assert goal["conversions"] >= 1

    @patch(
        "posthoganalytics.feature_enabled",
        new=Mock(side_effect=lambda key, *args, **kwargs: key == "hogql-warehouse-access-control"),
    )
    def test_userless_digest_reads_a_goal_that_filters_on_a_warehouse_table(self):
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="subscriptions",
            query={"kind": "HogQLQuery", "query": "SELECT 'a@example.com' AS customer_email, 'pro' AS plan"},
            columns={"customer_email": "String", "plan": "String"},
        )
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name="subscriptions",
            joining_table_key="customer_email",
            field_name="subscriptions",
        )
        Action.objects.create(
            team=self.team,
            name="Subscribed",
            steps_json=[
                {
                    "event": "signed_up",
                    "properties": [
                        {
                            "type": "data_warehouse_person_property",
                            "key": "subscriptions.plan",
                            "value": "pro",
                            "operator": "exact",
                        }
                    ],
                }
            ],
            last_calculated_at=timezone.now(),
        )

        with time_machine.travel(QUERY_TIMESTAMP, tick=False):
            result = get_goals_for_team(self.team)

        assert [goal["name"] for goal in result] == ["Subscribed"]


class TestBuildTeamDigest(ClickhouseTestMixin, APIBaseTest):
    def test_returns_all_expected_keys(self):
        with time_machine.travel(QUERY_TIMESTAMP, tick=False):
            _create_person(team_id=self.team.pk, distinct_ids=["user_1"])
            session = str(uuid7("2025-01-25"))
            _create_pageview(
                self.team, distinct_id="user_1", session_id=session, url="https://example.com/", timestamp="2025-01-25"
            )
            flush_persons_and_events()

            result = build_team_digest(self.team)

        assert result["team"] == self.team
        assert "top_pages" in result
        assert "top_sources" in result
        assert "goals" in result
        assert "dashboard_url" in result
        assert "utm_source=web_analytics_weekly_digest" in result["dashboard_url"]
        assert f"/project/{self.team.pk}/web" in result["dashboard_url"]

    def test_works_with_no_events(self):
        with time_machine.travel(QUERY_TIMESTAMP, tick=False):
            result = build_team_digest(self.team)

        assert result["team"] == self.team
        assert result["visitors"] == {"current": 0, "previous": None, "change": None}
        assert result["pageviews"] == {"current": 0, "previous": None, "change": None}
        assert result["sessions"] == {"current": 0, "previous": None, "change": None}
        assert result["bounce_rate"] == {"current": 0.0, "previous": None, "change": None}
        assert result["avg_session_duration"] == {"current": "0s", "previous": "0s", "change": None}
        assert result["top_pages"] == []
        assert result["top_sources"] == []
        assert result["goals"] == []
