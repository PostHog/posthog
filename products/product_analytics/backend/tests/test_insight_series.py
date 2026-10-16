from datetime import datetime, timedelta
from typing import Any, cast

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, User

from products.access_control.backend.facade.testing import create_access_control
from products.product_analytics.backend import insight_series
from products.product_analytics.backend.facade.api import get_insight_series
from products.product_analytics.backend.facade.contracts import InsightDashboardContext
from products.product_analytics.backend.insight_series import _visible
from products.product_analytics.backend.models.insight import Insight


class TestVisibleResults(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "by value",
                None,
                {'{"series":1,"breakdown_value":["Chrome"]}': {"hidden": True}},
                ["0 Chrome", "1 Safari"],
            ),
            ("by position", "position", {"2": {"hidden": True}}, ["0 Chrome", "1 Chrome"]),
            (
                "a visible customization",
                None,
                {'{"series":0,"breakdown_value":["Chrome"]}': {"color": "preset-2"}},
                ["0 Chrome", "1 Chrome", "1 Safari"],
            ),
        ]
    )
    def test_hidden_trend_results_are_left_out(
        self, _name: str, by: str | None, customizations: dict[str, Any], expected: list[str]
    ) -> None:
        results = [
            {"action": {"order": order}, "breakdown_value": browser}
            for order, browser in ((1, "Chrome"), (1, "Safari"), (0, "Chrome"))
        ]

        visible = _visible({"resultCustomizationBy": by, "resultCustomizations": customizations}, results)

        self.assertEqual(sorted(f"{r['action']['order']} {r['breakdown_value']}" for r in visible), expected)


def _result(label: str, breakdown: Any = None, **action: Any) -> dict[str, Any]:
    return {
        "action": {"name": "signed up", "order": 0, **action},
        "label": label,
        "breakdown_value": breakdown,
        "days": ["2026-10-12"],
        "data": [1],
    }


class TestSeriesNames(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "a cohort breakdown shows the cohort name",
                1,
                [_result("Enterprise", 12), _result("Free", 13)],
                {"Enterprise": False, "Free": False},
            ),
            (
                "several series name each series once",
                2,
                [
                    _result("signed up - Chrome", "Chrome"),
                    _result("logged in - Chrome", "Chrome", name="logged in", custom_name="Logins"),
                ],
                {"signed up · Chrome": False, "Logins · Chrome": False},
            ),
            (
                "first group occurrences add up",
                3,
                [
                    _result("signed up", math="first_time_for_group"),
                    _result("signed up", math="first_matching_event_for_group", custom_name="Matches"),
                    _result("signed up", math="dau", custom_name="Daily people"),
                ],
                {"signed up": False, "Matches": False, "Daily people": True},
            ),
        ]
    )
    def test_series_names_and_averaging(
        self, _name: str, series_count: int, results: list[dict[str, Any]], expected: dict[str, bool]
    ) -> None:
        with patch.object(insight_series, "_run", return_value={"results": results}):
            found = insight_series.insight_series(
                cast(Team, None),
                cast(User, None),
                short_id="abc",
                name="Sign-ups",
                query={"kind": "TrendsQuery", "series": [{}] * series_count},
                dashboard=None,
            )

        assert found is not None
        self.assertEqual({name: name in found.averaged_series for name in found.series}, expected)


class TestGetInsightSeries(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        blocking = patch.object(
            insight_series, "EXECUTION_MODE", ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
        )
        blocking.start()
        self.addCleanup(blocking.stop)

    def _ago(self, days: int) -> datetime:
        return timezone.now() - timedelta(days=days)

    def _signups(self, *days_and_browsers: tuple[int, str]) -> None:
        _create_person(team=self.team, distinct_ids=["user-1"])
        for days, browser in days_and_browsers:
            _create_event(
                team=self.team,
                event="signed up",
                distinct_id="user-1",
                properties={"$browser": browser},
                timestamp=self._ago(days),
            )
        flush_persons_and_events()

    def _insight(self, **query: Any) -> Insight:
        return Insight.objects.create(
            team=self.team,
            name="Sign-ups",
            created_by=self.user,
            saved=True,
            query={"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", **query}},
        )

    def test_a_daily_trend_returns_each_series_with_its_averaging_and_display_format(self) -> None:
        self._signups((2, "Chrome"), (2, "Chrome"), (9, "Chrome"))
        insight = self._insight(
            series=[
                {"kind": "EventsNode", "event": "signed up", "custom_name": "Sign-ups"},
                {"kind": "EventsNode", "event": "signed up", "math": "dau", "custom_name": "Daily people"},
            ],
            trendsFilter={"aggregationAxisFormat": "percentage", "display": "Metric", "decimalPlaces": 1_000_000},
        )

        found = get_insight_series(team=self.team, user=self.user, short_id=insight.short_id)

        assert found is not None
        self.assertEqual(
            (
                found.period,
                found.averaged_series,
                found.value_format,
                found.decimal_places,
                {name: (len(points), sum(v for _, v in points)) for name, points in found.series.items()},
            ),
            ("day", ["Daily people"], "percentage", 9, {"Sign-ups": (56, 3.0), "Daily people": (56, 2.0)}),
        )

    def test_a_smoothed_trend_returns_its_raw_daily_counts(self) -> None:
        self._signups((9, "Chrome"), (10, "Chrome"), (11, "Chrome"))
        insight = self._insight(
            series=[{"kind": "EventsNode", "event": "signed up"}], trendsFilter={"smoothingIntervals": 7}
        )

        found = get_insight_series(team=self.team, user=self.user, short_id=insight.short_id)

        assert found is not None
        self.assertEqual(sum(v for _, v in found.series["signed up"]), 3.0)

    def test_a_dashboard_filter_replaces_the_insight_filter_and_the_interval(self) -> None:
        self._signups((9, "Safari"), (10, "Safari"), (11, "Chrome"))
        insight = self._insight(
            series=[{"kind": "EventsNode", "event": "signed up"}],
            properties=[{"key": "$browser", "value": "Chrome", "operator": "exact", "type": "event"}],
        )
        dashboard = InsightDashboardContext(
            filters={
                "date_from": "-1d",
                "interval": "week",
                "properties": [{"key": "$browser", "value": "Safari", "operator": "exact", "type": "event"}],
            }
        )

        found = get_insight_series(team=self.team, user=self.user, short_id=insight.short_id, dashboard=dashboard)

        assert found is not None
        self.assertEqual((found.period, sum(v for _, v in found.series["signed up"])), ("week", 2.0))

    @parameterized.expand(
        [
            ("a table", {"kind": "TrendsQuery", "series": [], "trendsFilter": {"display": "ActionsTable"}}),
            ("a funnel", {"kind": "FunnelsQuery", "series": []}),
            (
                "a SQL insight",
                {"kind": "HogQLQuery", "query": "SELECT toDate(timestamp), count() FROM events GROUP BY 1"},
            ),
            (
                "a slope graph",
                {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "signed up"}],
                    "trendsFilter": {"display": "SlopeGraph"},
                },
            ),
            (
                "a daily trend on weekdays only",
                {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "signed up"}],
                    "dateRange": {"daysOfWeek": [1, 2, 3, 4, 5]},
                },
            ),
        ]
    )
    def test_an_insight_without_a_trend_series_returns_none(self, _name: str, source: dict[str, Any]) -> None:
        insight = Insight.objects.create(team=self.team, query={"kind": "InsightVizNode", "source": source})

        self.assertIsNone(get_insight_series(team=self.team, user=self.user, short_id=insight.short_id))

    def test_a_query_that_is_not_cached_yet_returns_none_and_does_not_block(self) -> None:
        self._signups((2, "Chrome"))
        insight = self._insight(series=[{"kind": "EventsNode", "event": "signed up"}])

        with (
            patch.object(insight_series, "EXECUTION_MODE", ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE),
            patch("posthog.hogql_queries.query_runner.QueryRunner.enqueue_async_calculation") as enqueue,
        ):
            found = get_insight_series(team=self.team, user=self.user, short_id=insight.short_id)

        self.assertEqual((found, enqueue.call_count), (None, 1))

    def test_an_insight_the_person_cannot_view_returns_none(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        insight = self._insight(series=[{"kind": "EventsNode", "event": "signed up"}])
        create_access_control(
            team_id=self.team.id, resource="insight", resource_id=str(insight.id), access_level="none"
        )
        reader = self._create_user("reader@example.com")

        self.assertIsNone(get_insight_series(team=self.team, user=reader, short_id=insight.short_id))
