from datetime import datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.hogql_queries.query_runner import ExecutionMode

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
            trendsFilter={"aggregationAxisFormat": "percentage"},
        )

        found = get_insight_series(team=self.team, user=self.user, short_id=insight.short_id)

        assert found is not None
        self.assertEqual(
            (
                found.period,
                found.averaged_series,
                found.value_format,
                {name: (len(points), sum(v for _, v in points)) for name, points in found.series.items()},
            ),
            ("day", ["Daily people"], "percentage", {"Sign-ups": (57, 3.0), "Daily people": (57, 2.0)}),
        )

    def test_a_dashboard_filter_replaces_the_insight_filter_on_the_same_property(self) -> None:
        self._signups((2, "Safari"), (3, "Safari"), (4, "Chrome"))
        insight = self._insight(
            series=[{"kind": "EventsNode", "event": "signed up"}],
            properties=[{"key": "$browser", "value": "Chrome", "operator": "exact", "type": "event"}],
        )
        dashboard = InsightDashboardContext(
            filters={
                "date_from": "-1d",
                "properties": [{"key": "$browser", "value": "Safari", "operator": "exact", "type": "event"}],
            }
        )

        found = get_insight_series(team=self.team, user=self.user, short_id=insight.short_id, dashboard=dashboard)

        assert found is not None
        self.assertEqual(sum(v for _, v in found.series["signed up"]), 2.0)

    @parameterized.expand(
        [
            ("a table", {"kind": "TrendsQuery", "series": [], "trendsFilter": {"display": "ActionsTable"}}),
            ("a funnel", {"kind": "FunnelsQuery", "series": []}),
            (
                "a SQL insight",
                {"kind": "HogQLQuery", "query": "SELECT toDate(timestamp), count() FROM events GROUP BY 1"},
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
