from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any, Optional

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    BreakdownFilter,
    ChartDisplayType,
    CompareFilter,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    IntervalType,
    PropertyOperator,
    RetentionFilter,
    RetentionQuery,
    TrendsFilter,
    TrendsQuery,
    WebVitalsQuery,
)

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, reset_query_tags, tag_queries
from posthog.hogql_queries.insights.trends.trends_query_runner import TrendsQueryRunner
from posthog.hogql_queries.query_runner import get_query_runner_or_none

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries.web_vitals_timeseries import WebVitalsQueryRunner
from products.web_analytics.backend.hogql_queries.web_vitals_timeseries_lazy_precompute import (
    is_vitals_precompute_enabled_for_team,
    vitals_timeseries_percentile,
)

_METRICS = ["INP", "LCP", "CLS", "FCP"]


def _series(
    metric: str,
    math: str = "p90",
    math_property: Optional[str] = None,
    math_multiplier: Optional[float] = None,
) -> EventsNode:
    return EventsNode(
        event="$web_vitals",
        name="$web_vitals",
        custom_name=metric,
        math=math,
        math_property=math_property or f"$web_vitals_{metric}_value",
        math_multiplier=math_multiplier,
    )


def _vitals_query(**overrides: Any) -> WebVitalsQuery:
    source_kwargs: dict[str, Any] = {
        "dateRange": DateRange(date_from="2024-01-01", date_to="2024-01-07"),
        "series": [_series(m) for m in _METRICS],
        "properties": [],
        "filterTestAccounts": False,
    }
    source_kwargs.update(overrides.pop("source_overrides", {}))
    wrapper_kwargs: dict[str, Any] = {"properties": []}
    wrapper_kwargs.update(overrides)
    return WebVitalsQuery(
        source=TrendsQuery(**source_kwargs),
        **wrapper_kwargs,
    )


class TestVitalsTimeseriesGate(APIBaseTest):
    def test_canonical_tab_shape_is_servable(self) -> None:
        assert vitals_timeseries_percentile(_vitals_query()) == "p90"
        # The tab query the frontend builds pins the line-graph display explicitly.
        assert (
            vitals_timeseries_percentile(
                _vitals_query(
                    source_overrides={"trendsFilter": TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH)}
                )
            )
            == "p90"
        )

    @parameterized.expand(
        [
            ("p95_not_stored", {"source_overrides": {"series": [_series(m, math="p95") for m in _METRICS]}}),
            (
                "mixed_percentiles",
                {
                    "source_overrides": {
                        "series": [_series("INP", math="p75")] + [_series(m, math="p90") for m in _METRICS[1:]]
                    }
                },
            ),
            ("missing_series", {"source_overrides": {"series": [_series(m) for m in _METRICS[:3]]}}),
            (
                "wrong_math_property",
                {"source_overrides": {"series": [_series(m, math_property="$other") for m in _METRICS]}},
            ),
            ("hour_interval", {"source_overrides": {"interval": IntervalType.HOUR}}),
            (
                "total_value_display",
                {"source_overrides": {"trendsFilter": TrendsFilter(display=ChartDisplayType.ACTIONS_BAR_VALUE)}},
            ),
            (
                "math_multiplier",
                {"source_overrides": {"series": [_series(m, math_multiplier=2.0) for m in _METRICS]}},
            ),
            ("sampled_source", {"source_overrides": {"samplingFactor": 0.5}}),
            (
                "weekday_filtered_range",
                {
                    "source_overrides": {
                        "dateRange": DateRange(date_from="2024-01-01", date_to="2024-01-07", daysOfWeek=[1, 2, 3])
                    }
                },
            ),
            (
                "breakdown",
                {"source_overrides": {"breakdownFilter": BreakdownFilter(breakdown="$browser")}},
            ),
            ("compare", {"source_overrides": {"compareFilter": CompareFilter(compare=True)}}),
        ]
    )
    def test_non_canonical_shapes_fall_back(self, _name: str, overrides: dict[str, Any]) -> None:
        assert vitals_timeseries_percentile(_vitals_query(**overrides)) is None

    def test_flag_check_fails_closed_on_evaluation_error(self) -> None:
        # The gate runs in dispatch and cache-key generation, outside the
        # calculation fallback handler, so a flag-evaluation error must return
        # False (use the live path) rather than fail the request.
        with patch(
            "products.web_analytics.backend.hogql_queries.web_vitals_timeseries_lazy_precompute.posthoganalytics.feature_enabled",
            side_effect=Exception("flag service unavailable"),
        ):
            assert is_vitals_precompute_enabled_for_team(self.team) is False


@override_settings(IN_UNIT_TESTING=True)
class TestWebVitalsTimeseriesLazyPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        sync_execute("SYSTEM STOP TTL MERGES sharded_web_vitals_paths_preaggregated")

    @contextmanager
    def _enable(self) -> Iterator[None]:
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common.posthoganalytics.feature_enabled",
                    return_value=True,
                )
            )
            stack.enter_context(
                patch(
                    "products.web_analytics.backend.hogql_queries.web_vitals_timeseries_lazy_precompute.posthoganalytics.feature_enabled",
                    return_value=True,
                )
            )
            yield

    def _seed(self) -> None:
        # Vitals samples across two days and two paths — the read must merge
        # quantile states across paths into one per-day tab value.
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={})
        for day, path, inp, lcp in [
            ("2024-01-02T10:00:00Z", "/home", 120.0, 2100.0),
            ("2024-01-02T11:00:00Z", "/docs", 480.0, 3900.0),
            ("2024-01-03T09:00:00Z", "/home", 90.0, 1500.0),
        ]:
            _create_event(
                team=self.team,
                event="$web_vitals",
                distinct_id="p1",
                timestamp=day,
                properties={
                    "$pathname": path,
                    "$web_vitals_INP_value": inp,
                    "$web_vitals_LCP_value": lcp,
                    "$web_vitals_CLS_value": 0.05,
                    "$web_vitals_FCP_value": 900.0,
                },
            )

    def _warm(self, query: WebVitalsQuery) -> None:
        # Mimic the SWR revalidation task: under a warming trigger the ensure
        # runs inserts inline instead of check-only, building the buckets a
        # plain user read can then be served from.
        tag_queries(
            team_id=self.team.pk,
            trigger="webAnalyticsStaleRevalidation",
            feature=Feature.CACHE_WARMUP,
            product=Product.WEB_ANALYTICS,
        )
        try:
            WebVitalsQueryRunner(team=self.team, query=query).calculate()
        finally:
            reset_query_tags()

    @freeze_time("2024-01-15T12:00:00Z")
    def test_precomputed_matches_live_trends(self) -> None:
        self._seed()
        query = _vitals_query()
        source = query.source
        assert isinstance(source, TrendsQuery)

        live = TrendsQueryRunner(team=self.team, query=source).calculate()

        with self._enable():
            self._warm(query)
            precomputed = WebVitalsQueryRunner(team=self.team, query=query).calculate()

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() > 0
        # The live path stamps printed HogQL on the response; the bucket path
        # never does. A None here proves the serve did not silently fall back.
        assert precomputed.hogql is None
        assert live.hogql is not None
        assert len(precomputed.results) == len(live.results) == 4
        for live_series, pre_series in zip(live.results, precomputed.results):
            assert pre_series["days"] == live_series["days"]
            assert pre_series["data"] == live_series["data"], live_series["action"]["custom_name"]
            assert pre_series["action"]["custom_name"] == live_series["action"]["custom_name"]

    @freeze_time("2024-01-15T12:00:00Z")
    def test_dispatch_routes_only_when_flag_enabled(self) -> None:
        query = _vitals_query().model_dump(mode="json")

        runner = get_query_runner_or_none(query, self.team)
        assert runner is None  # Flag off: no runner branch, legacy source unwrap.

        with patch(
            "products.web_analytics.backend.hogql_queries.web_vitals_timeseries_lazy_precompute.posthoganalytics.feature_enabled",
            return_value=True,
        ):
            runner = get_query_runner_or_none(query, self.team)
        assert isinstance(runner, WebVitalsQueryRunner)

    def test_dispatch_skips_runner_for_non_line_display(self) -> None:
        # Non-line displays (here a calendar heatmap) have dedicated trends
        # runners the plain-trends WebVitals runner can't reproduce, so with the
        # flag on the wrapper must still unwrap to its source rather than route
        # here.
        query = _vitals_query(
            source_overrides={"trendsFilter": TrendsFilter(display=ChartDisplayType.CALENDAR_HEATMAP)}
        ).model_dump(mode="json")
        with patch(
            "products.web_analytics.backend.hogql_queries.web_vitals_timeseries_lazy_precompute.posthoganalytics.feature_enabled",
            return_value=True,
        ):
            runner = get_query_runner_or_none(query, self.team)
        assert runner is None

    def test_dispatch_skips_runner_for_non_trends_source(self) -> None:
        # A schema-valid non-Trends source must fall through to the legacy source
        # unwrap, not raise in the runner constructor (which would surface as an
        # internal error rather than running the query).
        query = WebVitalsQuery(source=RetentionQuery(retentionFilter=RetentionFilter()), properties=[]).model_dump(
            mode="json"
        )
        with patch(
            "products.web_analytics.backend.hogql_queries.web_vitals_timeseries_lazy_precompute.posthoganalytics.feature_enabled",
            return_value=True,
        ):
            runner = get_query_runner_or_none(query, self.team)
        assert runner is None

    def test_cache_payload_carries_flag_state_as_kill_switch(self) -> None:
        query = _vitals_query()
        runner = WebVitalsQueryRunner(team=self.team, query=query)
        assert runner.get_cache_payload()["web_vitals_timeseries_precompute"] is False
        with self._enable():
            assert runner.get_cache_payload()["web_vitals_timeseries_precompute"] is True

    def test_cache_payload_varies_with_wrapper_filters(self) -> None:
        # The precompute read builds its jobs from the wrapper's own properties,
        # so two wrappers sharing a source but differing in outer filters must
        # not share a cache entry.
        base = WebVitalsQueryRunner(team=self.team, query=_vitals_query())
        filtered = WebVitalsQueryRunner(
            team=self.team,
            query=_vitals_query(
                properties=[EventPropertyFilter(key="$host", value="a.com", operator=PropertyOperator.EXACT)]
            ),
        )
        assert (
            base.get_cache_payload()["web_vitals_wrapper_properties"]
            != filtered.get_cache_payload()["web_vitals_wrapper_properties"]
        )
