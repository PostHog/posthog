"""Read-path parity: routing the web-analytics query runner to the dimensional
precompute tables (for enrolled teams) must produce the same results as the v2
pre-aggregated tables — including under multi-dimension filters, the capability
the fixed-dimension tables exist to provide.

The write-path parity test (`test_web_dimensional_precompute_parity`) asserts the
dimensional table *contents* equal v2's. This test instead drives the query
*runner* end-to-end, so it covers the read path the write-path test doesn't: the
query-builder table selection and the `job_id IN` dedup filter applied through
`StatsTablePreAggregatedQueryBuilder`.
"""

from datetime import UTC, datetime

from freezegun import freeze_time
from posthog.test.base import _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    PropertyOperator,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.clickhouse.client import sync_execute
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import WEB_BOUNCES_INSERT_SQL, WEB_STATS_INSERT_SQL

from products.web_analytics.backend.hogql_queries.pre_aggregated.query_builder import WEB_STATS_DIMENSIONAL_READ_TABLE
from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner
from products.web_analytics.backend.hogql_queries.stats_table_pre_aggregated import StatsTablePreAggregatedQueryBuilder
from products.web_analytics.backend.hogql_queries.test.web_preaggregated_test_base import (
    WebAnalyticsPreAggregatedTestBase,
)
from products.web_analytics.backend.hogql_queries.web_dimensional_precompute import (
    ensure_web_bounces_dimensional_precomputed,
    ensure_web_stats_dimensional_precomputed,
)

DATE_FROM = "2024-01-01"
DATE_TO = "2024-01-02"
# A `date_to` of "2024-01-02" resolves to end-of-day, so the query spans the 01-01 and
# 01-02 daily windows. Precompute both so the read path's full-coverage gate is satisfied
# (events only land on 01-01; the 01-02 window precomputes to an empty, still-READY job).
WINDOW_START = datetime(2024, 1, 1, tzinfo=UTC)
WINDOW_END = datetime(2024, 1, 3, tzinfo=UTC)


class TestWebDimensionalReadParity(WebAnalyticsPreAggregatedTestBase):
    def setUp(self):
        # STOP TTL MERGES before any data lands, so born-expired parts (the test's
        # frozen window is years behind the real CH clock) survive until we read.
        sync_execute("SYSTEM STOP TTL MERGES sharded_web_stats_dimensional_preaggregated")
        sync_execute("SYSTEM STOP TTL MERGES sharded_web_bounces_dimensional_preaggregated")
        super().setUp()

    def _pageview(self, distinct_id: str, session: str, ts: str, **props) -> None:
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=distinct_id,
            timestamp=ts,
            properties={"$session_id": session, **props},
        )

    def _setup_test_data(self):
        # Two hosts × device types so a host+device filter is a real cross-section.
        sa, sb, sc = (str(uuid7("2024-01-01")) for _ in range(3))
        with freeze_time("2024-01-01T09:00:00Z"):
            for did in ("user_a", "user_b", "user_c"):
                _create_person(team_id=self.team.pk, distinct_ids=[did])
            app_desktop = {
                "$host": "app.example.com",
                "$device_type": "Desktop",
                "$browser": "Chrome",
                "$os": "Windows",
                "$viewport_width": 1920,
                "$viewport_height": 1080,
            }
            # user_a: two pageviews on app.example.com / Desktop (non-bounce).
            self._pageview("user_a", sa, "2024-01-01T10:00:00Z", **{**app_desktop, "$pathname": "/"})
            self._pageview("user_a", sa, "2024-01-01T10:03:00Z", **{**app_desktop, "$pathname": "/pricing"})
            # user_b: single pageview on app.example.com / Mobile (bounce).
            self._pageview(
                "user_b",
                sb,
                "2024-01-01T11:00:00Z",
                **{
                    "$host": "app.example.com",
                    "$device_type": "Mobile",
                    "$browser": "Safari",
                    "$os": "iOS",
                    "$viewport_width": 390,
                    "$viewport_height": 844,
                    "$pathname": "/",
                },
            )
            # user_c: single pageview on blog.example.com / Desktop.
            self._pageview(
                "user_c",
                sc,
                "2024-01-01T12:00:00Z",
                **{
                    "$host": "blog.example.com",
                    "$device_type": "Desktop",
                    "$browser": "Firefox",
                    "$os": "Linux",
                    "$viewport_width": 1280,
                    "$viewport_height": 720,
                    "$pathname": "/blog",
                },
            )
            flush_persons_and_events()

        # Populate v2 and dimensional over the same window. ensure_* runs at real
        # time, so the jobs' expires_at is genuinely in the future and READY.
        for table, insert_sql in (
            ("web_pre_aggregated_stats", WEB_STATS_INSERT_SQL),
            ("web_pre_aggregated_bounces", WEB_BOUNCES_INSERT_SQL),
        ):
            sync_execute(
                insert_sql(
                    date_start=DATE_FROM,
                    date_end=DATE_TO,
                    team_ids=[self.team.pk],
                    table_name=table,
                    granularity="hourly",
                )
            )
        ensure_web_stats_dimensional_precomputed(self.team, WINDOW_START, WINDOW_END)
        ensure_web_bounces_dimensional_precomputed(self.team, WINDOW_START, WINDOW_END)

    def _query(self, breakdown: WebStatsBreakdown, properties=None) -> WebStatsTableQuery:
        return WebStatsTableQuery(
            dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
            properties=properties or [],
            breakdownBy=breakdown,
            limit=100,
        )

    def _run(self, breakdown: WebStatsBreakdown, properties=None) -> list:
        query = self._query(breakdown, properties)
        runner = WebStatsTableQueryRunner(
            query=query,
            team=self.team,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True),
        )
        response = runner.calculate()
        assert runner.used_preaggregated_tables, "expected the pre-aggregated path, not a live fallback"
        return self._sort_results(response.results)

    @staticmethod
    def _counts(results: list) -> dict:
        # {breakdown_value: (visitors, views)} — anchors values so a both-routes-broken
        # case can't pass on equality alone.
        return {row[0]: (row[1][0], row[2][0]) for row in results}

    def _assert_routes_to_dimensional(self, breakdown: WebStatsBreakdown, properties=None) -> None:
        runner = WebStatsTableQueryRunner(team=self.team, query=self._query(breakdown, properties))
        builder = StatsTablePreAggregatedQueryBuilder(runner)
        assert builder.use_dimensional_tables(), "enrolled team with READY data should route to dimensional"
        assert builder.stats_table == WEB_STATS_DIMENSIONAL_READ_TABLE

    @parameterized.expand(
        [
            # No filter — Desktop: user_a (2 views) + user_c (1 view) = 2 visitors / 3 views; Mobile: user_b = 1 / 1.
            ("device_breakdown", None, {"Desktop": (2.0, 3.0), "Mobile": (1.0, 1.0)}),
            # Host + device cross-section the fixed-dimension tables uniquely serve: blog.example.com / user_c is
            # excluded, leaving only the two app.example.com sessions.
            (
                "host_and_device_filter",
                [EventPropertyFilter(key="$host", value="app.example.com", operator=PropertyOperator.EXACT)],
                {"Desktop": (1.0, 2.0), "Mobile": (1.0, 1.0)},
            ),
        ]
    )
    def test_dimensional_matches_v2(self, _name, properties, expected_counts):
        with override_settings(WEB_DIMENSIONAL_PRECOMPUTE_TEAM_IDS=[]):
            v2 = self._run(WebStatsBreakdown.DEVICE_TYPE, properties=properties)
        with override_settings(WEB_DIMENSIONAL_PRECOMPUTE_TEAM_IDS=[self.team.pk]):
            self._assert_routes_to_dimensional(WebStatsBreakdown.DEVICE_TYPE, properties=properties)
            dimensional = self._run(WebStatsBreakdown.DEVICE_TYPE, properties=properties)

        assert dimensional == v2, f"{_name} mismatch\nv2={v2}\ndimensional={dimensional}"
        assert self._counts(dimensional) == expected_counts

    def test_partial_coverage_falls_back_to_v2(self):
        # Dimensional is precomputed for 2024-01-01 only (setUp). A window that also
        # spans 2024-01-02 is only partially covered, so the runner must fall back to
        # v2 rather than silently drop the uncovered day via the job_id filter.
        runner = WebStatsTableQueryRunner(
            team=self.team,
            query=WebStatsTableQuery(
                dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-03"),
                properties=[],
                breakdownBy=WebStatsBreakdown.DEVICE_TYPE,
                limit=100,
            ),
        )
        builder = StatsTablePreAggregatedQueryBuilder(runner)
        with override_settings(WEB_DIMENSIONAL_PRECOMPUTE_TEAM_IDS=[self.team.pk]):
            assert not builder.use_dimensional_tables(), "partial coverage must not route to dimensional"
            assert builder.stats_table == "web_pre_aggregated_stats"
