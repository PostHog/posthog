from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    CompareFilter,
    CustomEventConversionGoal,
    DateRange,
    EventPropertyFilter,
    PropertyOperator,
    WebAnalyticsOrderByDirection,
    WebAnalyticsOrderByFields,
    WebAnalyticsSampling,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.clickhouse.client import sync_execute
from posthog.models.utils import uuid7

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner

# Low-cardinality breakdowns with a generic seed that have data and are cheap to
# assert parity on. VIEWPORT is exercised separately — the raw query compares
# viewport tuple elements against 0, which needs numeric properties the test
# harness does not materialize.
PARITY_BREAKDOWNS = [
    ("browser", WebStatsBreakdown.BROWSER),
    ("os", WebStatsBreakdown.OS),
    ("device_type", WebStatsBreakdown.DEVICE_TYPE),
    ("country", WebStatsBreakdown.COUNTRY),
    ("region", WebStatsBreakdown.REGION),
    ("channel_type", WebStatsBreakdown.INITIAL_CHANNEL_TYPE),
    ("initial_referring_domain", WebStatsBreakdown.INITIAL_REFERRING_DOMAIN),
]


@override_settings(IN_UNIT_TESTING=True)
class TestWebStatsLazyPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        # The lazy framework derives `expires_at` from the (frozen) test clock, so
        # precompute rows are "born expired" relative to the real ClickHouse server
        # clock. Stop TTL merges on the precompute table so those parts are not
        # dropped in the window between the precompute INSERT and the read.
        sync_execute("SYSTEM STOP TTL MERGES sharded_web_stats_preaggregated")

    def _enable_lazy(self):
        # Mock the org-level feature flag check to True. Outside this context
        # manager the default `posthoganalytics.feature_enabled` returns False
        # (no API key in tests), which models a flag-disabled org.
        return patch(
            "products.web_analytics.backend.hogql_queries.web_analytics_lazy_precompute.posthoganalytics.feature_enabled",
            return_value=True,
        )

    def _props(self, **overrides) -> dict:
        base = {
            "$browser": "Chrome",
            "$os": "Linux",
            "$device_type": "Desktop",
            "$geoip_country_code": "US",
            "$geoip_subdivision_1_code": "US-CA",
            "$geoip_subdivision_1_name": "California",
            "$viewport_width": 1920,
            "$viewport_height": 1080,
            "$referring_domain": "google.com",
        }
        base.update(overrides)
        return base

    def _seed(self) -> None:
        # u1: session s1 (two pageviews /a /b) + session s3 (one pageview /a).
        # u2: session s2 (one pageview /x) with different dimensions.
        s1 = str(uuid7("2024-01-02"))
        s2 = str(uuid7("2024-01-03"))
        s3 = str(uuid7("2024-01-04"))
        _create_person(team_id=self.team.pk, distinct_ids=["u1"], properties={"name": "u1"})
        _create_person(team_id=self.team.pk, distinct_ids=["u2"], properties={"name": "u2"})

        for path, ts in (("/a", "2024-01-02T10:00:00Z"), ("/b", "2024-01-02T10:05:00Z")):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="u1",
                timestamp=ts,
                properties=self._props(
                    **{
                        "$session_id": s1,
                        "$host": "example.com",
                        "$current_url": f"https://example.com{path}",
                        "$pathname": path,
                    }
                ),
            )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="u2",
            timestamp="2024-01-03T11:00:00Z",
            properties=self._props(
                **{
                    "$session_id": s2,
                    "$host": "other.com",
                    "$current_url": "https://other.com/x",
                    "$pathname": "/x",
                    "$browser": "Firefox",
                    "$os": "Windows",
                    "$device_type": "Mobile",
                    "$geoip_country_code": "GB",
                    "$geoip_subdivision_1_code": "GB-ENG",
                    "$geoip_subdivision_1_name": "England",
                    "$viewport_width": 375,
                    "$viewport_height": 667,
                }
            ),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="u1",
            timestamp="2024-01-04T09:00:00Z",
            properties=self._props(
                **{
                    "$session_id": s3,
                    "$host": "example.com",
                    "$current_url": "https://example.com/a",
                    "$pathname": "/a",
                }
            ),
        )

    def _build_query(
        self,
        breakdown_by: WebStatsBreakdown = WebStatsBreakdown.BROWSER,
        date_from: str = "2024-01-01",
        date_to: str = "2024-01-07",
        properties: list | None = None,
        compare: bool = False,
        conversion_goal=None,
        sampling: WebAnalyticsSampling | None = None,
        include_bounce_rate: bool = False,
        include_avg_time_on_page: bool = False,
        include_scroll_depth: bool = False,
        opt_in_precompute: bool = True,
    ) -> WebStatsTableQuery:
        return WebStatsTableQuery(
            breakdownBy=breakdown_by,
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties or [],
            compareFilter=CompareFilter(compare=compare) if compare else None,
            conversionGoal=conversion_goal,
            sampling=sampling,
            includeBounceRate=include_bounce_rate,
            includeAvgTimeOnPage=include_avg_time_on_page,
            includeScrollDepth=include_scroll_depth,
            useWebAnalyticsPrecompute=opt_in_precompute,
        )

    def _run(self, query: WebStatsTableQuery):
        return WebStatsTableQueryRunner(team=self.team, query=query).calculate()

    @staticmethod
    def _metrics(response) -> list:
        # Breakdown value + visitors/views tuples, ignoring the fill-fraction
        # float (computed differently in SQL vs Python) and the cross_sell column.
        return [(row[0], tuple(row[1]), tuple(row[2])) for row in response.results]

    def _job_count(self) -> int:
        return PreaggregationJob.objects.filter(team_id=self.team.pk).count()

    @freeze_time("2024-01-15T12:00:00Z")
    def test_round_trip_creates_precompute_job(self):
        self._seed()
        with self._enable_lazy():
            self._run(self._build_query())

        assert self._job_count() > 0, "expected at least one precompute job to be created"

    @parameterized.expand(PARITY_BREAKDOWNS)
    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_matches_raw(self, _name: str, breakdown_by: WebStatsBreakdown):
        self._seed()

        raw = self._metrics(self._run(self._build_query(breakdown_by=breakdown_by)))

        with self._enable_lazy():
            lazy_response = self._run(self._build_query(breakdown_by=breakdown_by))
        lazy = self._metrics(lazy_response)

        ready_jobs = PreaggregationJob.objects.filter(
            team_id=self.team.pk, status=PreaggregationJob.Status.READY
        ).count()
        assert ready_jobs > 0, f"expected a READY precompute job for {breakdown_by}"
        assert lazy_response.usedLazyPrecompute is True
        assert lazy == raw, f"lazy/raw mismatch for {breakdown_by}: raw={raw}, lazy={lazy}"

    @parameterized.expand(PARITY_BREAKDOWNS)
    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_matches_raw_with_compare(self, _name: str, breakdown_by: WebStatsBreakdown):
        self._seed()
        # Previous period: one extra session for u1 in the 7 days before Jan 1.
        prev_session = str(uuid7("2023-12-28"))
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="u1",
            timestamp="2023-12-28T10:00:00Z",
            properties=self._props(
                **{
                    "$session_id": prev_session,
                    "$host": "example.com",
                    "$current_url": "https://example.com/old",
                    "$pathname": "/old",
                }
            ),
        )

        raw = self._metrics(self._run(self._build_query(breakdown_by=breakdown_by, compare=True)))

        with self._enable_lazy():
            lazy = self._metrics(self._run(self._build_query(breakdown_by=breakdown_by, compare=True)))

        assert lazy == raw, f"lazy/raw compare mismatch for {breakdown_by}: raw={raw}, lazy={lazy}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_viewport_breakdown_lazy_runs(self):
        # The raw VIEWPORT query compares viewport tuple elements against 0,
        # which needs numeric properties the harness does not materialize — so
        # this exercises the lazy path on its own rather than asserting parity.
        self._seed()
        with self._enable_lazy():
            response = self._run(self._build_query(breakdown_by=WebStatsBreakdown.VIEWPORT))

        assert response.usedLazyPrecompute is True
        assert len(response.results) > 0
        assert all(isinstance(row[0], tuple) and len(row[0]) == 2 for row in response.results)

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

    @freeze_time("2024-01-15T12:00:00Z")
    def test_host_filter_lazy_matches_raw(self):
        self._seed()
        host_filter = EventPropertyFilter(key="$host", value="example.com", operator=PropertyOperator.EXACT)

        raw = self._metrics(self._run(self._build_query(properties=[host_filter])))
        with self._enable_lazy():
            lazy = self._metrics(self._run(self._build_query(properties=[host_filter])))

        assert lazy == raw, f"host-filtered lazy/raw mismatch: raw={raw}, lazy={lazy}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_distinct_breakdowns_get_distinct_cache_entries(self):
        self._seed()
        with self._enable_lazy():
            self._run(self._build_query(breakdown_by=WebStatsBreakdown.BROWSER))
            browser_jobs = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}
            PreaggregationJob.objects.filter(team_id=self.team.pk).delete()

            self._run(self._build_query(breakdown_by=WebStatsBreakdown.OS))
            os_jobs = {str(j.query_hash) for j in PreaggregationJob.objects.filter(team_id=self.team.pk)}

        assert browser_jobs.isdisjoint(os_jobs), "different breakdowns must produce distinct cache keys"

    @parameterized.expand(
        [
            ("bounce_rate", {"include_bounce_rate": True}),
            ("avg_time_on_page", {"include_avg_time_on_page": True}),
            ("scroll_depth", {"include_scroll_depth": True}),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_extra_metric_falls_through(self, _name: str, kwargs: dict):
        self._seed()
        with self._enable_lazy():
            self._run(self._build_query(breakdown_by=WebStatsBreakdown.BROWSER, **kwargs))

        assert self._job_count() == 0, "extra metrics are not precomputed — must fall through to raw"

    @parameterized.expand(
        [
            ("page", WebStatsBreakdown.PAGE),
            ("initial_page", WebStatsBreakdown.INITIAL_PAGE),
            ("exit_click", WebStatsBreakdown.EXIT_CLICK),
            ("initial_referring_url", WebStatsBreakdown.INITIAL_REFERRING_URL),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_high_cardinality_breakdown_falls_through(self, _name: str, breakdown_by: WebStatsBreakdown):
        # Page/path/referring-URL breakdowns are intentionally excluded — too
        # high cardinality for the in-Python read. They fall through to raw.
        self._seed()
        with self._enable_lazy():
            self._run(self._build_query(breakdown_by=breakdown_by))

        assert self._job_count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_language_breakdown_falls_through(self):
        # LANGUAGE needs an extra topK aggregation column that can't be rebuilt
        # from hourly states — it must fall through to the raw path.
        self._seed()
        with self._enable_lazy():
            self._run(self._build_query(breakdown_by=WebStatsBreakdown.LANGUAGE))

        assert self._job_count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_conversion_goal_falls_through(self):
        self._seed()
        with self._enable_lazy():
            self._run(
                self._build_query(conversion_goal=CustomEventConversionGoal(customEventName="$pageview")),
            )

        assert self._job_count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_sampling_falls_through(self):
        self._seed()
        with self._enable_lazy():
            self._run(self._build_query(sampling=WebAnalyticsSampling(enabled=True)))

        assert self._job_count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_half_hour_offset_timezone_falls_through(self):
        self.team.timezone = "Asia/Kolkata"
        self.team.save()
        self._seed()
        with self._enable_lazy():
            self._run(self._build_query())

        assert self._job_count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_query_optin_alone_falls_through_when_org_flag_disabled(self):
        self._seed()
        self._run(self._build_query(opt_in_precompute=True))

        assert self._job_count() == 0

    @freeze_time("2024-01-15T12:00:00Z")
    def test_org_flag_alone_falls_through_when_query_not_opted_in(self):
        self._seed()
        with self._enable_lazy():
            self._run(self._build_query(opt_in_precompute=False))

        assert self._job_count() == 0

    @parameterized.expand([("utc", "UTC"), ("pacific", "America/Los_Angeles"), ("tokyo", "Asia/Tokyo")])
    @freeze_time("2024-01-15T12:00:00Z")
    def test_lazy_matches_raw_for_whole_hour_timezones(self, _name: str, team_tz: str):
        self.team.timezone = team_tz
        self.team.save()
        self._seed()

        raw = self._metrics(self._run(self._build_query()))
        with self._enable_lazy():
            lazy = self._metrics(self._run(self._build_query()))

        assert lazy == raw, f"lazy/raw mismatch for {team_tz}: raw={raw}, lazy={lazy}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_pagination_lazy_matches_raw(self):
        self._seed()
        query = self._build_query(breakdown_by=WebStatsBreakdown.BROWSER)
        query.limit = 1
        query.offset = 1

        raw_response = self._run(query)
        with self._enable_lazy():
            lazy_response = self._run(query)

        assert self._metrics(lazy_response) == self._metrics(raw_response)
        assert lazy_response.hasMore == raw_response.hasMore
        assert lazy_response.limit == raw_response.limit
        assert lazy_response.offset == raw_response.offset

    @freeze_time("2024-01-15T12:00:00Z")
    def test_recomputation_picks_up_late_events(self):
        self._seed()
        with self._enable_lazy():
            first = self._metrics(self._run(self._build_query(breakdown_by=WebStatsBreakdown.BROWSER)))
            first_job_ids = set(PreaggregationJob.objects.filter(team_id=self.team.pk).values_list("id", flat=True))
            assert first_job_ids

            # A late pageview from a new browser after the cache was built.
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="u2",
                timestamp="2024-01-05T08:00:00Z",
                properties=self._props(
                    **{
                        "$session_id": str(uuid7("2024-01-05")),
                        "$host": "other.com",
                        "$current_url": "https://other.com/late",
                        "$pathname": "/late",
                        "$browser": "Safari",
                    }
                ),
            )
            # Simulate TTL expiry by dropping the READY job rows.
            PreaggregationJob.objects.filter(id__in=first_job_ids).delete()

            second = self._metrics(self._run(self._build_query(breakdown_by=WebStatsBreakdown.BROWSER)))

        assert any(row[0] == "Safari" for row in second), "recomputed result should include the late pageview"
        assert first != second

    @freeze_time("2024-01-15T12:00:00Z")
    def test_session_crossing_midnight_lazy_matches_raw(self):
        # A session whose pageviews straddle a UTC day boundary. Session-start
        # bucketing attributes the whole session to its start hour; the forward
        # pad lets the start day's job still see the post-midnight pageviews.
        self._seed()
        _create_person(team_id=self.team.pk, distinct_ids=["mid"], properties={"name": "mid"})
        mid_session = str(uuid7("2024-01-05"))
        for ts in ("2024-01-05T23:55:00Z", "2024-01-06T00:10:00Z"):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="mid",
                timestamp=ts,
                properties=self._props(
                    **{
                        "$session_id": mid_session,
                        "$host": "example.com",
                        "$current_url": "https://example.com/x",
                        "$pathname": "/x",
                        "$browser": "Safari",
                    }
                ),
            )

        raw = self._metrics(self._run(self._build_query(breakdown_by=WebStatsBreakdown.BROWSER)))
        with self._enable_lazy():
            lazy = self._metrics(self._run(self._build_query(breakdown_by=WebStatsBreakdown.BROWSER)))

        assert lazy == raw, f"midnight-crossing session mismatch: raw={raw}, lazy={lazy}"
        # Non-vacuous: the Safari session must have both pageviews counted.
        safari = next(r for r in raw if r[0] == "Safari")
        assert safari[2][0] == 2, f"expected 2 Safari views, got {safari}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_ui_fill_fraction_lazy_matches_raw(self):
        # Column index 3 is `context.columns.ui_fill_fraction` — recomputed in
        # Python on the lazy path, so assert parity with the raw SQL window fn.
        self._seed()
        raw_response = self._run(self._build_query(breakdown_by=WebStatsBreakdown.BROWSER))
        with self._enable_lazy():
            lazy_response = self._run(self._build_query(breakdown_by=WebStatsBreakdown.BROWSER))

        raw_fill = [row[3] for row in raw_response.results]
        lazy_fill = [row[3] for row in lazy_response.results]
        assert len(raw_fill) == len(lazy_fill) and len(raw_fill) > 0
        for raw_value, lazy_value in zip(raw_fill, lazy_fill):
            assert abs(raw_value - lazy_value) < 1e-9, f"ui_fill_fraction mismatch: raw={raw_fill}, lazy={lazy_fill}"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_views_desc_orderby_lazy_matches_raw(self):
        # Forwarding the user's orderBy through to ClickHouse: sorting by views
        # must beat the silent visitors fallback the original PR relied on.
        self._seed()
        query = self._build_query(breakdown_by=WebStatsBreakdown.BROWSER)
        query.orderBy = [WebAnalyticsOrderByFields.VIEWS, WebAnalyticsOrderByDirection.DESC]

        raw = self._metrics(self._run(query))
        with self._enable_lazy():
            lazy = self._metrics(self._run(query))

        assert lazy == raw, f"views-desc parity broken: raw={raw}, lazy={lazy}"
        views = [row[2][0] for row in lazy]
        assert views == sorted(views, reverse=True), f"lazy not actually sorted by views desc: {views}"

    @parameterized.expand(
        [
            ("bounce_rate", WebAnalyticsOrderByFields.BOUNCE_RATE),
            ("conversion_rate", WebAnalyticsOrderByFields.CONVERSION_RATE),
            ("average_scroll", WebAnalyticsOrderByFields.AVERAGE_SCROLL_PERCENTAGE),
        ]
    )
    @freeze_time("2024-01-15T12:00:00Z")
    def test_unsupported_orderby_falls_through(self, _name: str, field: WebAnalyticsOrderByFields):
        # Fields the precompute schema can't serve must skip lazy entirely, not
        # silently rewrite the sort to visitors.
        self._seed()
        query = self._build_query(breakdown_by=WebStatsBreakdown.BROWSER)
        query.orderBy = [field, WebAnalyticsOrderByDirection.DESC]
        with self._enable_lazy():
            response = self._run(query)

        assert self._job_count() == 0
        # Raw path leaves `usedLazyPrecompute` unset; the failure mode we're
        # guarding against is the lazy path silently serving with a rewritten sort.
        assert response.usedLazyPrecompute is not True

    @freeze_time("2024-01-15T12:00:00Z")
    def test_pagination_page_two_lazy_matches_raw(self):
        # The PR's original code sorted + sliced in Python from an arbitrary
        # `LIMIT 100` cut. With SQL pagination, page 2 must be a contiguous
        # extension of page 1 — assert by comparing limit=1/offset=N pages.
        self._seed()
        base = self._build_query(breakdown_by=WebStatsBreakdown.BROWSER)

        responses_raw, responses_lazy = [], []
        for offset in range(3):
            query = self._build_query(breakdown_by=WebStatsBreakdown.BROWSER)
            query.limit = 1
            query.offset = offset
            responses_raw.append(self._run(query))
            with self._enable_lazy():
                responses_lazy.append(self._run(query))

        raw_full = self._metrics(self._run(base))
        for offset, (raw_resp, lazy_resp) in enumerate(zip(responses_raw, responses_lazy)):
            assert self._metrics(lazy_resp) == self._metrics(raw_resp), (
                f"offset={offset}: lazy/raw mismatch raw={self._metrics(raw_resp)} lazy={self._metrics(lazy_resp)}"
            )
            assert lazy_resp.hasMore == raw_resp.hasMore
            if offset < len(raw_full):
                assert self._metrics(lazy_resp)[0] == raw_full[offset], "lazy page row must match unpaginated position"

    @freeze_time("2024-01-15T12:00:00Z")
    def test_high_cardinality_utm_source_orders_in_sql(self):
        # Veria's concern: with N>>page_size distinct UTM values, the read used
        # to materialize all rows + paginate in Python. With SQL pagination the
        # first page must come back ordered by the requested metric and the
        # `hasMore` flag must accurately reflect the long tail.
        _create_person(team_id=self.team.pk, distinct_ids=["bot"], properties={"name": "bot"})
        for i in range(40):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="bot",
                timestamp=f"2024-01-02T10:{i % 60:02d}:00Z",
                properties=self._props(
                    **{
                        "$session_id": str(uuid7("2024-01-02")),
                        "$host": "example.com",
                        "$current_url": "https://example.com/x",
                        "$pathname": "/x",
                        # Skew so source_0 has the most visitors, then source_1, etc.
                        "utm_source": f"source_{i % 8}",
                    }
                ),
            )

        query = self._build_query(
            breakdown_by=WebStatsBreakdown.INITIAL_UTM_SOURCE,
            date_from="2024-01-01",
            date_to="2024-01-03",
        )
        query.limit = 3

        with self._enable_lazy():
            lazy_response = self._run(query)

        lazy_metrics = self._metrics(lazy_response)
        assert lazy_response.usedLazyPrecompute is True
        assert lazy_response.hasMore is True, "should report more rows past the requested page"
        assert len(lazy_metrics) == 3
        # Visitors are monotonically non-increasing on the returned page.
        visitors = [row[1][0] for row in lazy_metrics]
        assert visitors == sorted(visitors, reverse=True), f"first page not ordered by visitors desc: {visitors}"
