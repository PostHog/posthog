from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    CustomEventConversionGoal,
    DateRange,
    EventPropertyFilter,
    PropertyOperator,
    WebAnalyticsPreComputeStrategy,
    WebAnalyticsSampling,
    WebVitalsMetric,
    WebVitalsMetricBand,
    WebVitalsPathBreakdownQuery,
    WebVitalsPercentile,
)

from posthog.clickhouse.client import sync_execute
from posthog.models.utils import uuid7

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries.web_vitals_path_breakdown import WebVitalsPathBreakdownQueryRunner

# (metric, percentile) parity matrix. Reservoir is unsaturated for these test
# sizes (≤8192 samples), so `quantilesMerge` is exact and matches the raw
# `quantile(p)` exactly.
PARITY_MATRIX = [
    (f"{metric.value}_{pct.value}", metric, pct) for metric in WebVitalsMetric for pct in WebVitalsPercentile
]


@override_settings(IN_UNIT_TESTING=True)
class TestWebVitalsPathsLazyPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        # The lazy framework derives `expires_at` from the (frozen) test clock,
        # so precompute rows are "born expired" relative to the real ClickHouse
        # server clock. Stop TTL merges on the precompute table so those parts
        # are not dropped in the window between the precompute INSERT and the
        # subsequent read.
        sync_execute("SYSTEM STOP TTL MERGES sharded_web_vitals_paths_preaggregated")

    def _enable_lazy(self):
        # Mock the org-level feature flag check to True. Outside this context
        # manager the default `posthoganalytics.feature_enabled` returns False
        # (no API key in tests), which models a flag-disabled org.
        return patch(
            "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common.posthoganalytics.feature_enabled",
            return_value=True,
        )

    def _seed(self) -> None:
        # Three paths with controlled metric values so band classification is
        # deterministic for LCP (good ≤2500, poor >4000):
        #   /fast → LCP 1000 (good)
        #   /mid  → LCP 3000 (needs_improvements)
        #   /slow → LCP 5000 (poor)
        # INP / CLS / FCP values are also seeded so per-metric parity tests
        # have data to read.
        _create_person(team_id=self.team.pk, distinct_ids=["u1"], properties={})

        paths_metrics: list[tuple[str, dict, str]] = [
            ("/fast", {"LCP": 1000, "INP": 50, "CLS": 0.02, "FCP": 800}, "2024-01-02T10:00:00Z"),
            ("/mid", {"LCP": 3000, "INP": 150, "CLS": 0.15, "FCP": 1800}, "2024-01-02T11:00:00Z"),
            ("/slow", {"LCP": 5000, "INP": 350, "CLS": 0.30, "FCP": 3500}, "2024-01-02T12:00:00Z"),
        ]
        for path, vitals, ts in paths_metrics:
            _create_event(
                team=self.team,
                event="$web_vitals",
                distinct_id="u1",
                timestamp=ts,
                properties={
                    "$pathname": path,
                    "$current_url": f"https://example.com{path}",
                    "$host": "example.com",
                    "$session_id": str(uuid7("2024-01-02")),
                    "$web_vitals_LCP_value": vitals["LCP"],
                    "$web_vitals_INP_value": vitals["INP"],
                    "$web_vitals_CLS_value": vitals["CLS"],
                    "$web_vitals_FCP_value": vitals["FCP"],
                },
            )

    def _build_query(
        self,
        *,
        metric: WebVitalsMetric = WebVitalsMetric.LCP,
        percentile: WebVitalsPercentile = WebVitalsPercentile.P75,
        date_from: str = "2024-01-01",
        date_to: str = "2024-01-07",
        properties: list | None = None,
        conversion_goal=None,
        sampling: WebAnalyticsSampling | None = None,
        opt_in_precompute: bool = True,
        thresholds: list[float] | None = None,
    ) -> WebVitalsPathBreakdownQuery:
        # Default thresholds picked so the LCP seed splits paths into 3 bands:
        # 1000 → good, 3000 → needs_improvements, 5000 → poor.
        return WebVitalsPathBreakdownQuery(
            metric=metric,
            percentile=percentile,
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            conversionGoal=conversion_goal,
            sampling=sampling,
            thresholds=thresholds if thresholds is not None else [2500.0, 4000.0],
            useWebAnalyticsPrecompute=opt_in_precompute,
        )

    def _run(self, query: WebVitalsPathBreakdownQuery):
        return WebVitalsPathBreakdownQueryRunner(team=self.team, query=query).calculate()

    @staticmethod
    def _band_paths(response, band: WebVitalsMetricBand) -> list[str]:
        result = response.results[0]
        items = getattr(result, band.value)
        return sorted(item.path for item in items)

    @staticmethod
    def _paths_with_values(response) -> dict[str, tuple[str, float]]:
        """Flatten the band-partitioned response into `path → (band, value)`."""
        out: dict[str, tuple[str, float]] = {}
        for band in WebVitalsMetricBand:
            items = getattr(response.results[0], band.value)
            for item in items:
                out[item.path] = (band.value, item.value)
        return out

    def _job_count(self) -> int:
        return PreaggregationJob.objects.filter(team_id=self.team.pk).count()

    @freeze_time("2024-01-15T12:00:00Z")
    def test_round_trip_creates_precompute_job(self):
        self._seed()
        with self._enable_lazy():
            response = self._run(self._build_query())
        assert response.preComputeStrategy == WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE
        assert self._job_count() > 0, "expected at least one precompute job to be created"

    @parameterized.expand(PARITY_MATRIX)
    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_matches_raw_per_metric_percentile(
        self, _name: str, metric: WebVitalsMetric, percentile: WebVitalsPercentile
    ):
        self._seed()

        raw = self._paths_with_values(self._run(self._build_query(metric=metric, percentile=percentile)))

        with self._enable_lazy():
            lazy_response = self._run(self._build_query(metric=metric, percentile=percentile))
        lazy = self._paths_with_values(lazy_response)

        assert lazy_response.preComputeStrategy == WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE
        assert lazy.keys() == raw.keys(), f"path set mismatch for {metric}/{percentile}: raw={raw}, lazy={lazy}"
        for path in raw:
            raw_band, raw_value = raw[path]
            lazy_band, lazy_value = lazy[path]
            assert raw_band == lazy_band, f"band mismatch for {path} {metric}/{percentile}: raw={raw}, lazy={lazy}"
            assert abs(raw_value - lazy_value) < 1e-6, (
                f"value mismatch for {path} {metric}/{percentile}: raw={raw_value}, lazy={lazy_value}"
            )

    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_classifies_bands_correctly(self):
        self._seed()
        with self._enable_lazy():
            response = self._run(self._build_query(metric=WebVitalsMetric.LCP, percentile=WebVitalsPercentile.P75))
        assert self._band_paths(response, WebVitalsMetricBand.GOOD) == ["/fast"]
        assert self._band_paths(response, WebVitalsMetricBand.NEEDS_IMPROVEMENTS) == ["/mid"]
        assert self._band_paths(response, WebVitalsMetricBand.POOR) == ["/slow"]

    @freeze_time("2024-01-15T12:00:00Z")
    def test_conversion_goal_falls_through(self):
        self._seed()
        with self._enable_lazy():
            response = self._run(
                self._build_query(conversion_goal=CustomEventConversionGoal(customEventName="$pageview")),
            )
        assert response.preComputeStrategy != WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE
        assert self._job_count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_sampling_falls_through(self):
        self._seed()
        with self._enable_lazy():
            response = self._run(self._build_query(sampling=WebAnalyticsSampling(enabled=True)))
        assert response.preComputeStrategy != WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE
        assert self._job_count() == 0

    @parameterized.expand(
        [
            ("sub_day", "2024-01-02T10:00:00", "2024-01-02T12:00:00"),
            ("start_misaligned", "2024-01-02T10:00:00", "2024-01-03T00:00:00"),
            ("end_misaligned", "2024-01-02T00:00:00", "2024-01-02T12:00:00"),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_explicit_sub_day_range_falls_through(self, _name: str, date_from: str, date_to: str):
        # Only `explicitDate=True` lets the query date range surface non-midnight
        # times; without it, the parser silently truncates to start/end of day.
        # The runner buckets per team-tz day, so the read filter would compare
        # an hour-precise range against day-aligned bucket keys and silently
        # return empty. Eligibility must reject these ranges.
        self._seed()
        query = self._build_query(date_from=date_from, date_to=date_to)
        query.dateRange = DateRange(date_from=date_from, date_to=date_to, explicitDate=True)
        with self._enable_lazy():
            response = self._run(query)
        assert response.preComputeStrategy != WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE
        assert self._job_count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_half_hour_offset_timezone_matches_raw(self):
        # Vitals buckets by team-tz day, so half-hour-offset timezones (IST +5:30
        # here) align cleanly and don't fall through to raw.
        self.team.timezone = "Asia/Kolkata"
        self.team.save()
        self._seed()

        raw = self._paths_with_values(self._run(self._build_query()))
        with self._enable_lazy():
            lazy_response = self._run(self._build_query())
        lazy = self._paths_with_values(lazy_response)

        assert lazy_response.preComputeStrategy == WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE
        assert raw == lazy, f"lazy/raw mismatch in IST: raw={raw}, lazy={lazy}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_query_optin_alone_falls_through_when_org_flag_disabled(self):
        self._seed()
        response = self._run(self._build_query(opt_in_precompute=True))
        assert response.preComputeStrategy != WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE
        assert self._job_count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_org_flag_alone_falls_through_when_query_not_opted_in(self):
        self._seed()
        with self._enable_lazy():
            response = self._run(self._build_query(opt_in_precompute=False))
        assert response.preComputeStrategy != WebAnalyticsPreComputeStrategy.LAZY_PRECOMPUTE
        assert self._job_count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_host_filter_gets_distinct_cache_entry(self):
        self._seed()
        host_filter = EventPropertyFilter(key="$host", value="example.com", operator=PropertyOperator.EXACT)

        with self._enable_lazy():
            self._run(self._build_query())
            unfiltered = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}
            PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

            self._run(self._build_query(properties=[host_filter]))
            filtered = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

        assert unfiltered and filtered
        assert unfiltered.isdisjoint(filtered), "host filter must produce a distinct cache key"

    @parameterized.expand([("utc", "UTC"), ("pacific", "America/Los_Angeles"), ("tokyo", "Asia/Tokyo")])
    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_matches_raw_for_whole_hour_timezones(self, _name: str, team_tz: str):
        self.team.timezone = team_tz
        self.team.save()
        self._seed()

        raw = self._paths_with_values(self._run(self._build_query()))
        with self._enable_lazy():
            lazy = self._paths_with_values(self._run(self._build_query()))

        assert raw == lazy, f"lazy/raw mismatch for {team_tz}: raw={raw}, lazy={lazy}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_returns_at_most_20_per_band(self):
        _create_person(team_id=self.team.pk, distinct_ids=["bulk_user"], properties={})
        # 25 distinct paths all classifying as "poor" (LCP 6000+).
        for i in range(25):
            _create_event(
                team=self.team,
                event="$web_vitals",
                distinct_id="bulk_user",
                timestamp=f"2024-01-02T10:{i:02d}:00Z",
                properties={
                    "$pathname": f"/bulk_{i}",
                    "$host": "example.com",
                    "$session_id": str(uuid7("2024-01-02")),
                    "$web_vitals_LCP_value": 6000 + i,
                },
            )

        with self._enable_lazy():
            response = self._run(self._build_query(metric=WebVitalsMetric.LCP))

        poor_items = response.results[0].poor
        assert len(poor_items) == 20, f"expected exactly 20 paths in poor band, got {len(poor_items)}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_stale_served_enqueues_background_revalidation(self):
        # Without the `result.stale` hook this family would serve stale for the whole
        # 6h grace and never refresh (the revalidate half of stale-while-revalidate).
        from posthog.clickhouse.query_tagging import reset_query_tags, tags_context

        from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationResult
        from products.web_analytics.backend.hogql_queries.web_vitals_paths_lazy_precompute import (
            execute_lazy_precomputed_read,
        )

        with (
            tags_context(),
            self._enable_lazy(),
            patch(
                "products.web_analytics.backend.hogql_queries.web_vitals_paths_lazy_precompute.ensure_web_vitals_paths_precomputed",
                return_value=LazyComputationResult(ready=True, job_ids=[], stale=True),
            ),
            patch(
                "products.web_analytics.backend.tasks.lazy_precompute_revalidation.revalidate_web_analytics_precompute.delay"
            ) as delay,
        ):
            reset_query_tags()
            runner = WebVitalsPathBreakdownQueryRunner(team=self.team, query=self._build_query())
            execute_lazy_precomputed_read(runner)

        assert delay.call_count == 1
        assert delay.call_args.kwargs["team_id"] == self.team.pk
