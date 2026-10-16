"""Read-path parity: routing the web-analytics query runner to the dimensional
precompute tables (for opted-in queries) must produce the same results as the v2
pre-aggregated tables — including under multi-dimension filters, the capability
the fixed-dimension tables exist to provide.

The write-path parity test (`test_web_dimensional_precompute_parity`) asserts the
dimensional table *contents* equal v2's. This test instead drives the query
*runner* end-to-end, so it covers the read path the write-path test doesn't: the
dimensional builder's table selection and the `job_id IN` dedup filter.
"""

from datetime import UTC, datetime

import time_machine
from posthog.test.base import _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    PropertyOperator,
    WebAnalyticsPreComputeStrategy,
    WebAnalyticsQueryModifiers,
    WebOverviewQuery,
    WebStatsBreakdown,
    WebStatsTableQuery,
    WebStatsTableQueryResponse,
)

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import WEB_BOUNCES_INSERT_SQL, WEB_STATS_INSERT_SQL

from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner
from products.web_analytics.backend.hogql_queries.test.web_preaggregated_test_base import (
    WebAnalyticsPreAggregatedTestBase,
)
from products.web_analytics.backend.hogql_queries.web_dimensional_precompute import (
    ensure_web_bounces_dimensional_precomputed,
    ensure_web_stats_dimensional_precomputed,
)
from products.web_analytics.backend.hogql_queries.web_dimensional_read import ready_dimensional_job_ids
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner

DATE_FROM = "2024-01-01"
DATE_TO = "2024-01-02"
# A `date_to` of "2024-01-02" resolves to end-of-day, so the query spans the 01-01 and
# 01-02 daily windows. Precompute both so the read path's full-coverage gate is satisfied
# (events only land on 01-01; the 01-02 window precomputes to an empty, still-READY job).
WINDOW_START = datetime(2024, 1, 1, tzinfo=UTC)
WINDOW_END = datetime(2024, 1, 3, tzinfo=UTC)

LEGACY = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)
OPT_IN = WebAnalyticsQueryModifiers(useDimensionalTables=True)


class TestWebDimensionalReadParity(WebAnalyticsPreAggregatedTestBase):
    def setUp(self):
        # STOP TTL MERGES before any data lands, so born-expired parts (the test's
        # frozen window is years behind the real CH clock) survive until we read.
        for table in ("sharded_web_stats_dimensional_preaggregated", "sharded_web_bounces_dimensional_preaggregated"):
            sync_execute(f"SYSTEM STOP TTL MERGES {table}")
            self.addCleanup(sync_execute, f"SYSTEM START TTL MERGES {table}")
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
        with time_machine.travel("2024-01-01T09:00:00Z", tick=False):
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

    def _run(
        self,
        breakdown: WebStatsBreakdown,
        modifiers: HogQLQueryModifiers | None,
        web_query_modifiers: WebAnalyticsQueryModifiers | None,
        properties=None,
    ) -> tuple[str, list, WebStatsTableQueryResponse]:
        runner = WebStatsTableQueryRunner(
            query=WebStatsTableQuery(
                dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
                properties=properties or [],
                breakdownBy=breakdown,
                limit=100,
                webQueryModifiers=web_query_modifiers,
            ),
            team=self.team,
            modifiers=modifiers,
        )
        response = runner.calculate()
        assert runner.used_preaggregated_tables, "expected the pre-aggregated path, not a live fallback"
        return runner.query_strategy(), self._sort_results(response.results), response

    @staticmethod
    def _counts(results: list) -> dict:
        # {breakdown_value: (visitors, views)} — anchors values so a both-routes-broken
        # case can't pass on equality alone.
        return {row[0]: (row[1][0], row[2][0]) for row in results}

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
        v2_strategy, v2, v2_response = self._run(WebStatsBreakdown.DEVICE_TYPE, LEGACY, None, properties=properties)
        # Only the request opt-in: the legacy modifier must not be needed to reach this path.
        dimensional_strategy, dimensional, dimensional_response = self._run(
            WebStatsBreakdown.DEVICE_TYPE, None, OPT_IN, properties=properties
        )

        assert v2_strategy == "stats_table_preaggregated"
        assert dimensional_strategy == "stats_table_dimensional"
        assert v2_response.preComputeStrategy == WebAnalyticsPreComputeStrategy.PRE_AGGREGATED
        assert dimensional_response.preComputeStrategy == WebAnalyticsPreComputeStrategy.PRE_AGGREGATED
        assert dimensional == v2, f"{_name} mismatch\nv2={v2}\ndimensional={dimensional}"
        assert self._counts(dimensional) == expected_counts

    @parameterized.expand(
        [
            ("legacy_on_falls_back_to_v2", LEGACY, True),
            ("legacy_off_falls_back_to_live", None, False),
        ]
    )
    def test_partial_coverage_does_not_read_dimensional(self, _name, modifiers, expect_v2):
        # Dimensional is precomputed for 2024-01-01 and 01-02 only (setUp). A window that
        # also spans 2024-01-03 is only partially covered, so the job_id filter would
        # silently drop the uncovered day. The runner must skip dimensional instead.
        runner = WebStatsTableQueryRunner(
            team=self.team,
            query=WebStatsTableQuery(
                dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-03"),
                properties=[],
                breakdownBy=WebStatsBreakdown.DEVICE_TYPE,
                limit=100,
                webQueryModifiers=OPT_IN,
            ),
            modifiers=modifiers,
        )
        assert ready_dimensional_job_ids(runner) is None, "partial coverage must not route to dimensional"

        runner.calculate()
        assert runner.used_preaggregated_tables is expect_v2
        if expect_v2:
            assert runner.query_strategy() == "stats_table_preaggregated"

    def test_overview_dimensional_matches_v2(self):
        def run(modifiers, web_query_modifiers):
            runner = WebOverviewQueryRunner(
                query=WebOverviewQuery(
                    dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
                    properties=[],
                    webQueryModifiers=web_query_modifiers,
                ),
                team=self.team,
                modifiers=modifiers,
            )
            with patch(
                "products.web_analytics.backend.hogql_queries.web_overview.execute_hogql_query",
                wraps=execute_hogql_query,
            ) as mock_execute:
                response = runner.calculate()
            return [call.kwargs["query_type"] for call in mock_execute.call_args_list], response

        v2_query_types, v2 = run(LEGACY, None)
        dimensional_query_types, dimensional = run(None, OPT_IN)

        assert v2_query_types == ["web_overview_preaggregated_query"]
        assert dimensional_query_types == ["web_overview_dimensional_query"]
        assert dimensional.preComputeStrategy == WebAnalyticsPreComputeStrategy.PRE_AGGREGATED
        assert [(item.key, item.value) for item in dimensional.results] == [
            (item.key, item.value) for item in v2.results
        ]
        # visitors, views, sessions: user_a has 2 pageviews, user_b and user_c have 1 each.
        assert [item.value for item in dimensional.results[:3]] == [3, 4, 3]
