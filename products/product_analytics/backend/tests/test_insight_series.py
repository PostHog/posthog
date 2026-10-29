from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.schema import QueryStatus

from posthog.constants import AvailableFeature
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, User
from posthog.week_start_day import WeekStartDay

from products.access_control.backend.facade.testing import create_access_control
from products.actions.backend.models.action import Action
from products.product_analytics.backend import insight_series
from products.product_analytics.backend.facade.api import get_insight_series
from products.product_analytics.backend.facade.contracts import InsightDashboardContext
from products.product_analytics.backend.insight_series import _visible
from products.product_analytics.backend.models.insight import Insight


class TestBoundedInsightQuery(SimpleTestCase):
    @parameterized.expand(
        [
            ("cached", True, False, False, 0.0, 0),
            ("finishes", False, True, False, 0.0, 1),
            ("fails", False, True, True, 0.0, 1),
            ("still_running", False, False, False, 0.0, 3),
            ("starts_near_deadline", False, False, False, 0.5, 1),
            ("already_expired", False, False, False, 0.6, 0),
        ]
    )
    def test_wait_returns_results_or_stops_at_the_shared_deadline(
        self, _name: str, cached: bool, complete: bool, error: bool, start: float, polls: int
    ) -> None:
        clock = [start]
        results = {"results": [_result("signed up")]}
        pending = {"query_status": {"id": "query-1", "complete": False}}

        def advance(seconds: float) -> None:
            clock[0] += seconds

        with (
            patch("posthog.api.services.query.process_query_dict", return_value=results if cached else pending) as run,
            patch.object(insight_series, "monotonic", side_effect=lambda: clock[0]),
            patch.object(insight_series, "sleep", side_effect=advance),
            patch.object(
                insight_series,
                "get_query_status",
                return_value=QueryStatus(
                    id="query-1", team_id=1, complete=complete, error=error, results=results if complete else None
                ),
            ) as status,
        ):
            found = insight_series.insight_series(
                cast(Team, SimpleNamespace(pk=1)),
                cast(User, None),
                short_id="abc",
                name="Sign-ups",
                query={"kind": "TrendsQuery", "series": [SIGNED_UP]},
                dashboard=None,
                blocking=True,
                wait_until=0.6,
            )

        self.assertEqual(found is not None and bool(found.series), cached or (complete and not error))
        self.assertEqual(status.call_count, polls)
        self.assertLessEqual(clock[0], 0.6)
        self.assertEqual(run.call_args.kwargs["execution_mode"], ExecutionMode.RECENT_CACHE_CALCULATE_ASYNC_IF_STALE)


class TestVisibleResults(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "by value",
                None,
                {'{"series":1,"breakdown_value":["Chrome"]}': {"hidden": True}},
                None,
                ["0 Chrome", "1 Safari"],
            ),
            ("by position", "position", {"2": {"hidden": True}}, None, ["0 Chrome", "1 Chrome"]),
            (
                "a visible customization",
                None,
                {'{"series":0,"breakdown_value":["Chrome"]}': {"color": "preset-2"}},
                None,
                ["0 Chrome", "1 Chrome", "1 Safari"],
            ),
            (
                "a formula row is keyed by its formula, not the series at its order",
                None,
                {'{"series":1,"breakdown_value":["Chrome"]}': {"hidden": True}},
                [{"formula": "A+B"}, {"formula": "A-B"}],
                ["0 Chrome", "1 Chrome", "1 Safari"],
            ),
        ]
    )
    def test_hidden_trend_results_are_left_out(
        self,
        _name: str,
        by: str | None,
        customizations: dict[str, Any],
        formula_nodes: list[dict[str, Any]] | None,
        expected: list[str],
    ) -> None:
        results = [
            {"order": order, "breakdown_value": browser}
            for order, browser in ((1, "Chrome"), (1, "Safari"), (0, "Chrome"))
        ]
        query = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": "signed up"}, {"kind": "EventsNode", "event": "logged in"}],
            "trendsFilter": {
                "resultCustomizationBy": by,
                "resultCustomizations": customizations,
                "formulaNodes": formula_nodes,
            },
        }

        visible = _visible(query, results)

        self.assertEqual(sorted(f"{r['order']} {r['breakdown_value']}" for r in visible), expected)


SIGNED_UP = {"kind": "EventsNode", "event": "signed up", "name": "signed up"}


def _result(label: str, order: int = 0, breakdown: Any = None) -> dict[str, Any]:
    return {"label": label, "order": order, "breakdown_value": breakdown, "days": ["2026-10-12"], "data": [1]}


class TestSeriesNames(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "a cohort breakdown shows the cohort name",
                [SIGNED_UP],
                [_result("Enterprise", breakdown=12), _result("Free", breakdown=13)],
                {"Enterprise": False, "Free": False},
            ),
            (
                "several series name each series once",
                [SIGNED_UP, {"kind": "EventsNode", "event": "logged in", "name": "logged in", "custom_name": "Logins"}],
                [_result("signed up - Chrome", 0, "Chrome"), _result("logged in - Chrome", 1, "Chrome")],
                {"signed up · Chrome": False, "Logins · Chrome": False},
            ),
            (
                "a series saved without a kind takes its event",
                [{"event": "signed up"}],
                [_result("signed up")],
                {"signed up": False},
            ),
            (
                "first group occurrences add up",
                [
                    {**SIGNED_UP, "math": "first_time_for_group"},
                    {**SIGNED_UP, "math": "first_matching_event_for_group", "custom_name": "Matches"},
                    {**SIGNED_UP, "math": "dau", "custom_name": "Daily people"},
                ],
                [_result("signed up", 0), _result("signed up", 1), _result("signed up", 2)],
                {"signed up": False, "Matches": False, "Daily people": True},
            ),
        ]
    )
    def test_series_names_and_averaging(
        self, _name: str, series: list[dict[str, Any]], results: list[dict[str, Any]], expected: dict[str, bool]
    ) -> None:
        with patch.object(insight_series, "_run", return_value={"results": results}):
            found = insight_series.insight_series(
                cast(Team, None),
                cast(User, None),
                short_id="abc",
                name="Sign-ups",
                query={"kind": "TrendsQuery", "series": series},
                dashboard=None,
            )

        assert found is not None
        self.assertEqual({name: name in found.averaged_series for name in found.series}, expected)


def _sql_query(display: str = "ActionsLineGraph", **chart_settings: Any) -> dict[str, Any]:
    return {
        "kind": "DataVisualizationNode",
        "source": {"kind": "HogQLQuery", "query": "SELECT 1"},
        "display": display,
        "chartSettings": {"xAxis": {"column": "week"}, "yAxis": [{"column": "p50"}], **chart_settings},
    }


def _weekly(*rows: list[Any]) -> dict[str, Any]:
    return {"columns": ["week", "p50"], "results": list(rows)}


class TestSqlSeries(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "a weekly breakdown names each series by its column and value",
                _sql_query(yAxis=[{"column": "p50"}, {"column": "p90"}], seriesBreakdownColumn="kind"),
                {
                    "columns": ["week", "kind", "p50", "p90"],
                    "results": [["2026-10-04", "html", 1, 2], ["2026-10-11", "html", 3, 4]],
                },
                WeekStartDay.SUNDAY,
                ("week", {"p50 · html": [1.0, 3.0], "p90 · html": [2.0, 4.0]}, None, None),
            ),
            (
                "a null breakdown value stays apart from the text None",
                _sql_query(seriesBreakdownColumn="kind"),
                {
                    "columns": ["week", "kind", "p50"],
                    "results": [
                        ["2026-10-04", None, 1],
                        ["2026-10-04", "None", 2],
                        ["2026-10-11", None, 3],
                        ["2026-10-11", "None", 4],
                    ],
                },
                WeekStartDay.SUNDAY,
                ("week", {"[No value]": [1.0, 3.0], "None": [2.0, 4.0]}, None, None),
            ),
            (
                "a series with a null leaves the tile and keeps the others",
                _sql_query(yAxis=[{"column": "p50"}, {"column": "p90"}]),
                {
                    "columns": ["week", "p50", "p90"],
                    "results": [["2026-10-04", 1, 2], ["2026-10-11", 3, None]],
                },
                WeekStartDay.SUNDAY,
                ("week", {"p50": [1.0, 3.0]}, None, None),
            ),
            (
                "a chart that shows nulls as zero keeps the zero",
                _sql_query(showNullsAsZero=True),
                _weekly(["2026-10-04", 1], ["2026-10-11", None]),
                WeekStartDay.SUNDAY,
                ("week", {"p50": [1.0, 0.0]}, None, None),
            ),
            (
                "midnight timestamps are days",
                _sql_query(),
                _weekly(["2026-10-04T00:00:00-07:00", 1], ["2026-10-11T00:00:00-07:00", 2]),
                WeekStartDay.SUNDAY,
                ("week", {"p50": [1.0, 2.0]}, None, None),
            ),
            (
                "hourly timestamps are not days",
                _sql_query(),
                _weekly(["2026-10-01T10:00:00", 1], ["2026-10-02T13:00:00", 2]),
                WeekStartDay.SUNDAY,
                None,
            ),
            (
                "two columns that share a label keep both series",
                _sql_query(
                    yAxis=[
                        {"column": "a", "settings": {"display": {"label": "Users"}}},
                        {"column": "b", "settings": {"display": {"label": "Users"}}},
                        {"column": "c", "settings": {"display": {"label": "Users"}}},
                    ]
                ),
                {"columns": ["week", "a", "b", "c"], "results": [["2026-10-04", 1, 5, 7], ["2026-10-11", 2, 6, 8]]},
                WeekStartDay.SUNDAY,
                ("week", {"Users": [1.0, 2.0], "Users (2)": [5.0, 6.0], "Users (3)": [7.0, 8.0]}, None, None),
            ),
            (
                "weeks that start on Monday in a Monday project",
                _sql_query(),
                _weekly(["2026-09-28", 1], ["2026-10-05", 2]),
                WeekStartDay.MONDAY,
                ("week", {"p50": [1.0, 2.0]}, None, None),
            ),
            (
                "weeks that start on Monday in a Sunday project",
                _sql_query(),
                _weekly(["2026-09-28", 1], ["2026-10-05", 2]),
                WeekStartDay.SUNDAY,
                None,
            ),
            (
                "a monthly series keeps its label and currency prefix",
                _sql_query(
                    xAxis={"column": "month"},
                    yAxis=[
                        {
                            "column": "revenue",
                            "settings": {"display": {"label": "Revenue"}, "formatting": {"prefix": "$"}},
                        }
                    ],
                ),
                {"columns": ["month", "revenue"], "results": [["2026-08-01", 10], ["2026-09-01", 12]]},
                WeekStartDay.SUNDAY,
                ("month", {"Revenue": [10.0, 12.0]}, "$", None),
            ),
            (
                "a percent column is scaled like the chart",
                _sql_query(yAxis=[{"column": "rate", "settings": {"formatting": {"style": "percent"}}}]),
                {"columns": ["week", "rate"], "results": [["2026-10-04", 0.2], ["2026-10-11", 0.25]]},
                WeekStartDay.SUNDAY,
                ("week", {"rate": [0.2, 0.25]}, None, "percentage_scaled"),
            ),
            (
                "a table",
                _sql_query(display="ActionsTable"),
                _weekly(),
                WeekStartDay.SUNDAY,
                None,
            ),
            (
                "a truncated result",
                _sql_query(),
                {**_weekly(["2026-10-04", 1], ["2026-10-11", 2]), "hasMore": True},
                WeekStartDay.SUNDAY,
                None,
            ),
            (
                "rows that repeat a date",
                _sql_query(),
                _weekly(["2026-10-04", 1], ["2026-10-04", 2]),
                WeekStartDay.SUNDAY,
                None,
            ),
            (
                "an x axis that is not a date",
                _sql_query(),
                _weekly(["html", 1], ["react", 2]),
                WeekStartDay.SUNDAY,
                None,
            ),
            (
                "dates without a regular interval",
                _sql_query(),
                _weekly(["2026-10-04", 1], ["2026-10-07", 2]),
                WeekStartDay.SUNDAY,
                None,
            ),
            (
                "a missing week",
                _sql_query(),
                _weekly(["2026-09-20", 1], ["2026-09-27", 2], ["2026-10-11", 3]),
                WeekStartDay.SUNDAY,
                None,
            ),
            (
                "a missing month",
                _sql_query(),
                _weekly(["2026-07-01", 1], ["2026-09-01", 2]),
                WeekStartDay.SUNDAY,
                None,
            ),
        ]
    )
    def test_sql_insight_series(
        self,
        _name: str,
        query: dict[str, Any],
        response: dict[str, Any],
        week_start_day: WeekStartDay,
        expected: tuple[str, dict[str, list[float]], str | None, str | None] | None,
    ) -> None:
        with patch.object(insight_series, "_run", return_value=response):
            found = insight_series.insight_series(
                Team(week_start_day=week_start_day),
                cast(User, None),
                short_id="abc",
                name="Build time",
                query=query,
                dashboard=None,
            )

        summary = (
            None
            if found is None
            else (
                found.period,
                {name: [v for _, v in points] for name, points in found.series.items()},
                found.value_prefix,
                found.value_format,
            )
        )
        self.assertEqual(summary, expected)


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

    @override_settings(IN_UNIT_TESTING=True)
    def test_a_daily_trend_returns_each_series_with_its_averaging_and_display_format(self) -> None:
        self._signups((2, "Chrome"), (2, "Chrome"), (9, "Chrome"))
        action = Action.objects.create(team=self.team, name="Signed up action", steps_json=[{"event": "signed up"}])
        insight = self._insight(
            series=[
                {"kind": "EventsNode", "event": "signed up", "custom_name": "Sign-ups"},
                {"kind": "EventsNode", "event": "signed up", "math": "dau", "custom_name": "Daily people"},
                {"kind": "ActionsNode", "id": action.pk},
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
            (
                "day",
                ["Daily people"],
                "percentage",
                9,
                {"Sign-ups": (56, 3.0), "Daily people": (56, 2.0), "Signed up action": (56, 3.0)},
            ),
        )

    def test_a_charted_sql_insight_returns_its_daily_series(self) -> None:
        self._signups((2, "Chrome"), (2, "Chrome"), (3, "Chrome"))
        insight = Insight.objects.create(
            team=self.team,
            name="Sign-ups",
            saved=True,
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "SELECT toStartOfDay(timestamp) AS day, count() AS signups FROM events "
                    "WHERE event = 'signed up' GROUP BY day ORDER BY day",
                },
                "display": "ActionsLineGraph",
                "chartSettings": {"xAxis": {"column": "day"}, "yAxis": [{"column": "signups"}]},
            },
        )

        found = get_insight_series(team=self.team, user=self.user, short_id=insight.short_id)

        assert found is not None
        self.assertEqual(
            (found.period, found.averaged_series, found.series),
            ("day", ["signups"], {"signups": [(self._ago(3).date(), 1.0), (self._ago(2).date(), 2.0)]}),
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
