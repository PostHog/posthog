from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import (
    BreakdownFilter,
    ChartDisplayType,
    CompareFilter,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    IntervalType,
    SessionPropertyFilter,
    TrendsFilter,
    TrendsQuery,
)

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models.utils import uuid7

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries import web_trends_lazy_precompute
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner
from products.web_analytics.backend.hogql_queries.web_trends import WebTrendsQueryRunner
from products.web_analytics.backend.hogql_queries.web_trends_lazy_precompute import (
    WebTrendsMetric,
    _current_period_boundary,
    build_inner_overview_query,
    trends_precompute_metric,
)

_UTC = ZoneInfo("UTC")


def _d(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=_UTC)


class TestCurrentPeriodBoundary(SimpleTestCase):
    @parameterized.expand(
        [
            # The boundary is the start of the first still-evolving bucket. Below
            # it precompute serves; at or above it the live tail does. Snapping to
            # the containing week/month start is what sends a whole in-progress
            # period live instead of only its trailing day.
            (
                "day_today_in_range",
                [_d(2024, 1, x) for x in range(10, 17)],
                _d(2024, 1, 16),
                _d(2024, 1, 15),
                _d(2024, 1, 15),
            ),
            # Range ends before today: nothing is evolving, so the boundary sits
            # past every bucket and the whole range stays on precompute.
            (
                "fully_historical",
                [_d(2024, 1, x) for x in range(1, 8)],
                _d(2024, 1, 7),
                _d(2024, 1, 15),
                _d(2024, 1, 15),
            ),
            # Today is mid-week (Jan 17); the boundary snaps back to the Monday
            # bucket so the in-progress week reads live.
            (
                "week_snaps_back",
                [_d(2023, 12, 25), _d(2024, 1, 1), _d(2024, 1, 8), _d(2024, 1, 15)],
                _d(2024, 1, 17),
                _d(2024, 1, 17),
                _d(2024, 1, 15),
            ),
            (
                "month_snaps_back",
                [_d(2023, 11, 1), _d(2023, 12, 1), _d(2024, 1, 1)],
                _d(2024, 1, 15),
                _d(2024, 1, 15),
                _d(2024, 1, 1),
            ),
            # A single-bucket "today" range has no settled portion; the boundary
            # equals that bucket, and the caller falls fully back to live.
            ("today_only", [_d(2024, 1, 15)], _d(2024, 1, 15), _d(2024, 1, 15), _d(2024, 1, 15)),
            # Hourly range whose tail is today: the boundary is today's midnight,
            # so every hour of today reads live.
            (
                "hour_today",
                [_d(2024, 1, 14, h) for h in range(24)] + [_d(2024, 1, 15, h) for h in range(13)],
                _d(2024, 1, 15, 12),
                _d(2024, 1, 15),
                _d(2024, 1, 15),
            ),
        ]
    )
    def test_boundary(
        self, _name: str, buckets: list[datetime], date_to: datetime, today_start: datetime, expected: datetime
    ) -> None:
        assert _current_period_boundary(buckets, date_to, today_start) == expected


@override_settings(IN_UNIT_TESTING=True)
class TestWebTrendsLazyPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        # Precompute rows are "born expired" relative to the real ClickHouse
        # clock under freeze_time; stop TTL merges so they survive until read.
        sync_execute("SYSTEM STOP TTL MERGES sharded_web_overview_preaggregated")

    def _enable_lazy(self):
        return patch(
            "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common.posthoganalytics.feature_enabled",
            return_value=True,
        )

    def _enable_trends_flag(self):
        return override_settings(WEB_ANALYTICS_TRENDS_PRECOMPUTE_TEAM_IDS=[self.team.pk])

    def _seed(self) -> None:
        # p1: two-pageview session on Jan 2; p2: single-pageview bounce on Jan 3.
        # Sessions are fully inside single days so session-start attribution and
        # event-time attribution agree and both paths must return identical data.
        s1 = str(uuid7("2024-01-02"))
        s2 = str(uuid7("2024-01-03"))
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={})
        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={})
        for ts, url in (("2024-01-02T10:00:00Z", "/a"), ("2024-01-02T10:05:00Z", "/b")):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="p1",
                timestamp=ts,
                properties={"$session_id": s1, "$host": "example.com", "$current_url": f"https://example.com{url}"},
            )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2024-01-03T11:00:00Z",
            properties={"$session_id": s2, "$host": "other.com", "$current_url": "https://other.com/x"},
        )

    def _seed_span(self) -> None:
        # One historical day inside the range and one on the frozen "today"
        # (2024-01-15). Each is a single-day session, so session-start and
        # event-time attribution agree and both paths return identical data.
        for day, distinct, host in (("2024-01-12", "p_hist", "example.com"), ("2024-01-15", "p_today", "other.com")):
            _create_person(team_id=self.team.pk, distinct_ids=[distinct], properties={})
            sid = str(uuid7(day))
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id=distinct,
                timestamp=f"{day}T09:00:00Z",
                properties={"$session_id": sid, "$host": host, "$current_url": f"https://{host}/x"},
            )

    def _build_query(
        self,
        math: str = "dau",
        math_property: str | None = None,
        compare: bool = False,
        interval: IntervalType = IntervalType.DAY,
    ) -> TrendsQuery:
        return TrendsQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-07"),
            interval=interval,
            series=[
                EventsNode(
                    event="$pageview",
                    math=math,
                    math_property=math_property,
                    math_property_type="session_properties" if math_property else None,
                    custom_name="My metric",
                )
            ],
            trendsFilter=TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
            compareFilter=CompareFilter(compare=compare) if compare else None,
            properties=[],
        )

    @parameterized.expand(
        [
            # If the precompute read, zero-fill, or response assembly drifts
            # from the live trends contract, the tile silently renders wrong
            # numbers — this pins precompute output to the live runner's exact
            # data/days/labels for every servable metric.
            ("unique_users", "dau", None),
            ("views", "total", None),
            ("unique_sessions", "unique_session", None),
            ("avg_duration", "avg", "$session_duration"),
            ("bounce_rate", "avg", "$is_bounce"),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_precompute_matches_live_trends(self, _name: str, math: str, math_property: str | None) -> None:
        self._seed()
        query = self._build_query(math=math, math_property=math_property)

        live = TrendsQueryRunner(team=self.team, query=query).calculate()

        with self._enable_lazy(), self._enable_trends_flag():
            precomputed = WebTrendsQueryRunner(team=self.team, query=query).calculate()

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() > 0
        assert len(precomputed.results) == 1
        pre_series = precomputed.results[0]
        live_series = live.results[0]
        assert pre_series["data"] == live_series["data"]
        assert pre_series["days"] == live_series["days"]
        assert pre_series["labels"] == live_series["labels"]
        assert pre_series["count"] == live_series["count"]
        assert pre_series["label"] == live_series["label"]
        assert pre_series["action"]["custom_name"] == "My metric"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_compare_period_matches_live_trends(self) -> None:
        self._seed()
        query = self._build_query(compare=True)

        live = TrendsQueryRunner(team=self.team, query=query).calculate()

        with self._enable_lazy(), self._enable_trends_flag():
            precomputed = WebTrendsQueryRunner(team=self.team, query=query).calculate()

        assert len(precomputed.results) == len(live.results) == 2
        for pre_series, live_series in zip(precomputed.results, live.results):
            assert pre_series["compare_label"] == live_series["compare_label"]
            assert pre_series["data"] == live_series["data"]
            assert pre_series["days"] == live_series["days"]
            # The previous series' labels and action.days must use the CURRENT
            # range's context like the live runner does — the compare tooltip
            # pairs points across series by these.
            assert pre_series["labels"] == live_series["labels"]
            assert pre_series["action"]["days"] == live_series["action"]["days"]
        assert precomputed.resolved_compare_date_range is not None

    @freeze_time("2024-01-15T12:00:00Z")
    def test_reuses_overview_precompute_jobs(self) -> None:
        # The whole point of the inner-WebOverviewQuery mapping: trends reads
        # must find the buckets the overview tile already built, not mint a
        # parallel job namespace that doubles insert load.
        self._seed()
        with self._enable_lazy():
            overview_query = build_inner_overview_query(self._build_query(), [])
            WebOverviewQueryRunner(team=self.team, query=overview_query).calculate()
        jobs_after_overview = PreaggregationJob.objects.filter(team_id=self.team.pk).count()
        assert jobs_after_overview > 0

        with self._enable_lazy(), self._enable_trends_flag():
            precomputed = WebTrendsQueryRunner(team=self.team, query=self._build_query()).calculate()

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == jobs_after_overview
        assert sum(precomputed.results[0]["data"]) > 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_flag_off_falls_back_to_live_path(self) -> None:
        self._seed()
        trends_flag_off = patch(
            "products.web_analytics.backend.hogql_queries.web_trends_lazy_precompute.posthoganalytics.feature_enabled",
            return_value=False,
        )
        with self._enable_lazy(), trends_flag_off:
            response = WebTrendsQueryRunner(team=self.team, query=self._build_query()).calculate()

        # Fallback executed the standard trends path: no precompute jobs, and
        # the results still match the live contract.
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0
        assert sum(response.results[0]["data"]) == 2

    @parameterized.expand(
        [
            # Shapes the buckets can't reproduce must fall back — serving them
            # would silently return wrong numbers (e.g. a breakdown collapsed
            # to a single series, or WAU windowed math served as plain uniques).
            ("multi_series", {"series": [EventsNode(event="$pageview"), EventsNode(event="$pageleave")]}),
            ("non_pageview_event", {"series": [EventsNode(event="$autocapture", math="dau")]}),
            ("windowed_math", {"series": [EventsNode(event="$pageview", math="weekly_active")]}),
            (
                "unsupported_math_property",
                {
                    "series": [
                        EventsNode(event="$pageview", math="avg", math_property="$time", math_property_type="event")
                    ]
                },
            ),
            (
                # Same property name, event-level semantics — per-event avg, not
                # per-session; the buckets would silently serve the wrong number.
                "event_property_is_bounce",
                {
                    "series": [
                        EventsNode(
                            event="$pageview", math="avg", math_property="$is_bounce", math_property_type="event"
                        )
                    ]
                },
            ),
            ("breakdown", {"breakdownFilter": BreakdownFilter(breakdown="$browser", breakdown_type="event")}),
            (
                "world_map_display",
                {"trendsFilter": TrendsFilter(display=ChartDisplayType.WORLD_MAP)},
            ),
            (
                "formula",
                {"trendsFilter": TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH, formula="A / B")},
            ),
            ("minute_interval", {"interval": IntervalType.MINUTE}),
            (
                # The live path multiplies before averaging; buckets store raw
                # states, so a multiplier would be silently dropped.
                "math_multiplier",
                {
                    "series": [
                        EventsNode(
                            event="$pageview",
                            math="avg",
                            math_property="$session_duration",
                            math_property_type="session_properties",
                            math_multiplier=0.001,
                        )
                    ]
                },
            ),
        ]
    )
    def test_unservable_shapes_are_rejected(self, _name: str, overrides: dict) -> None:
        query = self._build_query().model_copy(update=overrides)
        assert trends_precompute_metric(query) is None

    def test_servable_shape_maps_to_metric(self) -> None:
        assert trends_precompute_metric(self._build_query()) is WebTrendsMetric.UNIQUE_USERS

    @freeze_time("2024-01-15T12:00:00Z")
    def test_session_filter_falls_back(self) -> None:
        # Session filters pass the shape gate but the shared eligibility check
        # rejects them (the precompute INSERT can't apply them faithfully).
        self._seed()
        query = self._build_query()
        query.properties = [SessionPropertyFilter(key="$channel_type", value=["Direct"], operator="exact")]
        with self._enable_lazy(), self._enable_trends_flag():
            WebTrendsQueryRunner(team=self.team, query=query).calculate()
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    def test_dispatch_routes_wa_tagged_trends_queries(self) -> None:
        # Dispatch requires BOTH the WA product tag and the rollout flag; with
        # the flag off even tagged queries must take the untouched vanilla path
        # (the flag is the zero-exposure kill switch for the whole runner).
        tagged = self._build_query().model_dump()
        tagged["tags"] = {"productKey": "web_analytics"}
        with self._enable_trends_flag():
            assert isinstance(get_query_runner(tagged, self.team), WebTrendsQueryRunner)

        flag_off = patch(
            "products.web_analytics.backend.hogql_queries.web_trends_lazy_precompute.posthoganalytics.feature_enabled",
            return_value=False,
        )
        with flag_off:
            runner = get_query_runner(tagged, self.team)
            assert isinstance(runner, TrendsQueryRunner)
            assert not isinstance(runner, WebTrendsQueryRunner)

        untagged = self._build_query()
        with self._enable_trends_flag():
            runner = get_query_runner(untagged, self.team)
        assert isinstance(runner, TrendsQueryRunner)
        assert not isinstance(runner, WebTrendsQueryRunner)

    @parameterized.expand(
        [
            # Each interval has its own bucket expression and days-format
            # branch; hour additionally exercises mid-day (non-day-floored)
            # read bounds against day-floored precompute jobs.
            ("hour", IntervalType.HOUR, "2024-01-02", "2024-01-03"),
            ("month", IntervalType.MONTH, "2024-01-01", "2024-01-31"),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_interval_parity_with_live_trends(
        self, _name: str, interval: IntervalType, date_from: str, date_to: str
    ) -> None:
        self._seed()
        query = self._build_query(interval=interval)
        query.dateRange = DateRange(date_from=date_from, date_to=date_to)

        live = TrendsQueryRunner(team=self.team, query=query).calculate()
        with self._enable_lazy(), self._enable_trends_flag():
            precomputed = WebTrendsQueryRunner(team=self.team, query=query).calculate()

        assert precomputed.results[0]["data"] == live.results[0]["data"]
        assert precomputed.results[0]["days"] == live.results[0]["days"]
        assert precomputed.results[0]["labels"] == live.results[0]["labels"]

    @freeze_time("2024-01-15T12:00:00Z")
    def test_filtered_round_trip_matches_live(self) -> None:
        # Filters must flow into the precompute INSERT and back out — if the
        # series-level merge in effective_properties or the inner query's
        # property mapping drops them, a $host-filtered tile silently shows
        # unfiltered fleet numbers.
        self._seed()
        host_filter = EventPropertyFilter(key="$host", value=["example.com"], operator="exact")
        query = self._build_query()
        query.properties = [host_filter]

        live = TrendsQueryRunner(team=self.team, query=query).calculate()
        with self._enable_lazy(), self._enable_trends_flag():
            precomputed = WebTrendsQueryRunner(team=self.team, query=query).calculate()
        assert precomputed.results[0]["data"] == live.results[0]["data"]
        assert sum(precomputed.results[0]["data"]) == 1  # only p1 on example.com

        # Same filter attached to the series node (how some WA tiles send it)
        # must produce the same served numbers.
        series_query = self._build_query()
        series_query.series[0].properties = [host_filter]
        with self._enable_lazy(), self._enable_trends_flag():
            series_filtered = WebTrendsQueryRunner(team=self.team, query=series_query).calculate()
        assert series_filtered.results[0]["data"] == precomputed.results[0]["data"]

    @freeze_time("2024-01-15T12:00:00Z")
    def test_distinct_id_aggregation_falls_back(self) -> None:
        # Vanilla trends counts distinct_ids for these teams while the buckets
        # store person-id uniq states — genuinely different numbers.
        self._seed()
        with (
            self._enable_lazy(),
            self._enable_trends_flag(),
            patch.object(type(self.team), "aggregate_users_by_distinct_id", property(lambda self: True)),
        ):
            WebTrendsQueryRunner(team=self.team, query=self._build_query()).calculate()
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_stale_buckets_are_served_and_revalidated_via_overview_family(self) -> None:
        # Stale-within-grace buckets must be served (falling back would put
        # dashboards on the slow path at every TTL lapse) and the background
        # revalidation must debounce under the web_overview family so one
        # rebuild refreshes the buckets both tiles read.
        self._seed()
        real_ensure = web_trends_lazy_precompute.ensure_web_overview_precomputed

        def stale_ensure(**kwargs):
            result = real_ensure(**kwargs)
            return replace(result, stale=True)

        with (
            self._enable_lazy(),
            self._enable_trends_flag(),
            patch(
                "products.web_analytics.backend.hogql_queries.web_trends_lazy_precompute.ensure_web_overview_precomputed",
                side_effect=stale_ensure,
            ),
            patch(
                "products.web_analytics.backend.hogql_queries.web_trends_lazy_precompute.handle_stale_served"
            ) as mock_stale,
        ):
            response = WebTrendsQueryRunner(team=self.team, query=self._build_query()).calculate()

        assert sum(response.results[0]["data"]) == 2  # served, not fallen back
        assert mock_stale.called
        assert mock_stale.call_args.kwargs["family"] == "web_overview"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_today_spanning_range_stitches_live_tail(self) -> None:
        # A range whose last bucket is "today": settled days come from precompute,
        # today comes from the live tail. If the tail merge keyed buckets wrong,
        # today would zero-fill and the served series would diverge from live.
        self._seed_span()
        query = self._build_query()
        query.dateRange = DateRange(date_from="2024-01-10", date_to="2024-01-15")

        live = TrendsQueryRunner(team=self.team, query=query).calculate()
        with self._enable_lazy(), self._enable_trends_flag():
            precomputed = WebTrendsQueryRunner(team=self.team, query=query).calculate()

        assert precomputed.results[0]["data"] == live.results[0]["data"]
        assert precomputed.results[0]["days"] == live.results[0]["days"]
        assert precomputed.results[0]["labels"] == live.results[0]["labels"]
        # Today (last bucket) is the live tail, not a zero-fill.
        assert precomputed.results[0]["data"][-1] == 1
        # Settled days were still precomputed — the path did not fully fall back.
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() > 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_today_only_range_falls_back_to_live(self) -> None:
        # The whole range is the in-progress day, so nothing is settled enough to
        # precompute: the path bails to live and mints no precompute jobs.
        self._seed_span()
        query = self._build_query()
        query.dateRange = DateRange(date_from="2024-01-15", date_to="2024-01-15")

        live = TrendsQueryRunner(team=self.team, query=query).calculate()
        with self._enable_lazy(), self._enable_trends_flag():
            precomputed = WebTrendsQueryRunner(team=self.team, query=query).calculate()

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0
        assert precomputed.results[0]["data"] == live.results[0]["data"]
        assert sum(precomputed.results[0]["data"]) == 1

    @freeze_time("2024-01-15T12:00:00Z")
    def test_week_interval_zero_fills_full_range(self) -> None:
        self._seed()
        query = self._build_query(interval=IntervalType.WEEK)
        live = TrendsQueryRunner(team=self.team, query=query).calculate()
        with self._enable_lazy(), self._enable_trends_flag():
            precomputed = WebTrendsQueryRunner(team=self.team, query=query).calculate()
        assert precomputed.results[0]["data"] == live.results[0]["data"]
        assert precomputed.results[0]["days"] == live.results[0]["days"]
