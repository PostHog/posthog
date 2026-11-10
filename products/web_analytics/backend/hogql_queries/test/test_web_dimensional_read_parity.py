from datetime import UTC, datetime

import pytest
import time_machine
from posthog.test.base import _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    CustomChannelCondition,
    CustomChannelField,
    CustomChannelOperator,
    CustomChannelRule,
    DateRange,
    EventPropertyFilter,
    FilterLogicalOperator,
    HogQLQueryModifiers,
    PropertyOperator,
    SessionPropertyFilter,
    WebAnalyticsPreComputeStrategy,
    WebAnalyticsQueryModifiers,
    WebOverviewQuery,
    WebStatsBreakdown,
    WebStatsTableQuery,
    WebStatsTableQueryResponse,
)

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client import sync_execute
from posthog.errors import CHQueryErrorQueryWasCancelled
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryTimeOut
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import WEB_BOUNCES_INSERT_SQL, WEB_STATS_INSERT_SQL

from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner
from products.web_analytics.backend.hogql_queries.stats_table_pre_aggregated import StatsTablePreAggregatedQueryBuilder
from products.web_analytics.backend.hogql_queries.test.web_preaggregated_test_base import (
    WebAnalyticsPreAggregatedTestBase,
)
from products.web_analytics.backend.hogql_queries.web_dimensional_precompute import (
    WEB_BOUNCES_DIMENSIONAL_READ_TABLE,
    WEB_STATS_DIMENSIONAL_READ_TABLE,
    ensure_web_bounces_dimensional_precomputed,
    ensure_web_stats_dimensional_precomputed,
)
from products.web_analytics.backend.hogql_queries.web_dimensional_read import ready_dimensional_job_ids
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner

DIMENSIONAL_READ_TABLES = (WEB_STATS_DIMENSIONAL_READ_TABLE, WEB_BOUNCES_DIMENSIONAL_READ_TABLE)

DATE_FROM = "2024-01-01"
DATE_TO = "2024-01-02"
# A `date_to` of "2024-01-02" resolves to end-of-day, so the query spans the 01-01 and
# 01-02 daily windows. Precompute both so the read path's full-coverage gate is satisfied
# (events only land on 01-01; the 01-02 window precomputes to an empty, still-READY job).
WINDOW_START = datetime(2024, 1, 1, tzinfo=UTC)
WINDOW_END = datetime(2024, 1, 3, tzinfo=UTC)

LEGACY = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True)
OPT_IN = WebAnalyticsQueryModifiers(useDimensionalTables=True)
UNTAGGED_CHANNEL = HogQLQueryModifiers(
    customChannelTypeRules=[
        CustomChannelRule(
            id="untagged",
            channel_type="Untagged",
            combiner=FilterLogicalOperator.AND_,
            items=[
                CustomChannelCondition(
                    id="source", key=CustomChannelField.UTM_SOURCE, op=CustomChannelOperator.IS_NOT_SET
                )
            ],
        )
    ]
)

PARTNER_URL_CHANNEL = CustomChannelRule(
    id="partner",
    channel_type="Partner",
    combiner=FilterLogicalOperator.AND_,
    items=[
        CustomChannelCondition(
            id="ref", key=CustomChannelField.URL, op=CustomChannelOperator.ICONTAINS, value="ref=partner"
        )
    ],
)


class TestWebDimensionalReadParity(WebAnalyticsPreAggregatedTestBase):
    def setUp(self):
        # STOP TTL MERGES before any data lands, so born-expired parts (the test's
        # frozen window is years behind the real CH clock) survive until we read.
        for table in ("sharded_web_stats_dimensional_preaggregated", "sharded_web_bounces_dimensional_preaggregated"):
            sync_execute(f"SYSTEM STOP TTL MERGES {table}")
            self.addCleanup(sync_execute, f"SYSTEM START TTL MERGES {table}")
        flag_patcher = patch(
            "products.web_analytics.backend.hogql_queries.web_dimensional_read.feature_enabled_or_false",
            return_value=True,
        )
        flag_patcher.start()
        self.addCleanup(flag_patcher.stop)
        variant_patcher = patch(
            "products.web_analytics.backend.hogql_queries.web_dimensional_read.get_feature_flag_or_none",
            return_value=None,
        )
        variant_patcher.start()
        self.addCleanup(variant_patcher.stop)
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
                "$browser_version": 120,
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
                    "$current_url": "https://blog.example.com/blog?ref=partner",
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
        include_bounce_rate: bool = False,
    ) -> tuple[str, list, WebStatsTableQueryResponse]:
        runner = WebStatsTableQueryRunner(
            query=WebStatsTableQuery(
                dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
                properties=properties or [],
                breakdownBy=breakdown,
                limit=100,
                webQueryModifiers=web_query_modifiers,
                includeBounceRate=include_bounce_rate,
            ),
            team=self.team,
            modifiers=modifiers,
        )
        response = runner.calculate()
        assert runner.used_preaggregated_tables, "expected the pre-aggregated path, not a live fallback"
        return runner.query_strategy(), self._sort_results(response.results), response

    def _run_live(self, breakdown: WebStatsBreakdown, properties=None, include_bounce_rate: bool = False) -> list:
        runner = WebStatsTableQueryRunner(
            query=WebStatsTableQuery(
                dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
                properties=properties or [],
                breakdownBy=breakdown,
                limit=100,
                includeBounceRate=include_bounce_rate,
            ),
            team=self.team,
        )
        response = runner.calculate()
        assert not runner.used_preaggregated_tables
        return self._sort_results(response.results)

    @staticmethod
    def _counts(results: list) -> dict:
        # {breakdown_value: (visitors, views)} — anchors values so a both-routes-broken
        # case can't pass on equality alone.
        return {row[0]: (row[1][0], row[2][0]) for row in results}

    @staticmethod
    def _bounce_rates(results: list) -> dict:
        return {row[0]: row[3][0] for row in results}

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
            (
                "device_breakdown_with_bounce_rate",
                None,
                {"Desktop": (2.0, 3.0), "Mobile": (1.0, 1.0)},
                {"Desktop": 0.5, "Mobile": 1.0},
            ),
            (
                "unset_utm_source_with_bounce_rate",
                None,
                {None: (3.0, 4.0)},
                {None: 2 / 3},
                WebStatsBreakdown.INITIAL_UTM_SOURCE,
            ),
        ]
    )
    def test_dimensional_matches_v2(
        self,
        _name,
        properties,
        expected_counts,
        expected_bounce_rates=None,
        breakdown=WebStatsBreakdown.DEVICE_TYPE,
    ):
        include_bounce_rate = expected_bounce_rates is not None
        v2_strategy, v2, v2_response = self._run(
            breakdown, LEGACY, None, properties=properties, include_bounce_rate=include_bounce_rate
        )
        # Only the request opt-in: the legacy modifier must not be needed to reach this path.
        dimensional_strategy, dimensional, dimensional_response = self._run(
            breakdown, None, OPT_IN, properties=properties, include_bounce_rate=include_bounce_rate
        )

        assert v2_strategy == "stats_table_preaggregated"
        assert dimensional_strategy == "stats_table_dimensional"
        assert v2_response.preComputeStrategy == WebAnalyticsPreComputeStrategy.PRE_AGGREGATED
        assert dimensional_response.preComputeStrategy == WebAnalyticsPreComputeStrategy.PRE_AGGREGATED
        assert dimensional_response.preComputedAt is not None
        assert dimensional_response.preComputeStale is None
        assert dimensional == v2, f"{_name} mismatch\nv2={v2}\ndimensional={dimensional}"
        assert self._counts(dimensional) == expected_counts
        live = self._run_live(breakdown, properties, include_bounce_rate=include_bounce_rate)
        assert self._counts(live) == expected_counts
        if include_bounce_rate:
            assert "context.columns.bounce_rate" in (dimensional_response.columns or [])
            assert self._bounce_rates(dimensional) == pytest.approx(expected_bounce_rates)
            assert self._bounce_rates(live) == pytest.approx(expected_bounce_rates)

    @parameterized.expand(
        [
            (
                "pathname_filter",
                WebStatsBreakdown.DEVICE_TYPE,
                [EventPropertyFilter(key="$pathname", value="/", operator=PropertyOperator.EXACT)],
                {"Desktop": 0.0, "Mobile": 1.0},
            ),
            ("viewport_breakdown", WebStatsBreakdown.VIEWPORT, [], None),
        ]
    )
    def test_bounce_rate_shape_skips_pre_aggregated_tables(self, _name, breakdown, properties, expected_bounce_rates):
        runner = WebStatsTableQueryRunner(
            team=self.team,
            query=WebStatsTableQuery(
                dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
                properties=properties,
                breakdownBy=breakdown,
                includeBounceRate=True,
                limit=100,
                webQueryModifiers=OPT_IN,
            ),
            modifiers=LEGACY,
        )

        assert not StatsTablePreAggregatedQueryBuilder(runner).can_use_preaggregated_tables()
        if expected_bounce_rates is not None:
            opted_in = self._sort_results(runner.calculate().results)
            assert not runner.used_preaggregated_tables
            assert opted_in == self._run_live(breakdown, properties, include_bounce_rate=True)
            assert self._bounce_rates(opted_in) == expected_bounce_rates

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
        assert ready_dimensional_job_ids(runner, DIMENSIONAL_READ_TABLES) is None, (
            "partial coverage must not route to dimensional"
        )

        runner.calculate()
        assert runner.used_preaggregated_tables is expect_v2
        if expect_v2:
            assert runner.query_strategy() == "stats_table_preaggregated"

    @parameterized.expand(
        [
            (
                "breakdown",
                WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
                [],
                {"Partner": (1.0, 1.0), "Unknown": (2.0, 3.0)},
            ),
            (
                "filter",
                WebStatsBreakdown.DEVICE_TYPE,
                [SessionPropertyFilter(key="$channel_type", value="Partner", operator=PropertyOperator.EXACT)],
                {"Desktop": (1.0, 1.0)},
            ),
        ]
    )
    def test_team_channel_rules_are_served_once_rebuilt(self, _name, breakdown, properties, expected_counts):
        self.team.modifiers = {"customChannelTypeRules": [PARTNER_URL_CHANNEL.model_dump(mode="json")]}
        self.team.save()

        def run():
            runner = WebStatsTableQueryRunner(
                team=self.team,
                query=WebStatsTableQuery(
                    dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
                    properties=properties,
                    breakdownBy=breakdown,
                    limit=100,
                    webQueryModifiers=OPT_IN,
                ),
            )
            return runner, self._sort_results(runner.calculate().results)

        stale_runner, _ = run()
        assert ready_dimensional_job_ids(stale_runner, DIMENSIONAL_READ_TABLES) is None

        ensure_web_stats_dimensional_precomputed(self.team, WINDOW_START, WINDOW_END)
        ensure_web_bounces_dimensional_precomputed(self.team, WINDOW_START, WINDOW_END)
        runner, dimensional = run()

        assert runner.used_preaggregated_tables
        assert runner.query_strategy() == "stats_table_dimensional"
        assert dimensional == self._run_live(breakdown, properties)
        assert self._counts(dimensional) == expected_counts

    @parameterized.expand(
        [
            (
                "custom_channel_breakdown",
                DateRange(date_from=DATE_FROM, date_to=DATE_TO),
                WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
                [],
                UNTAGGED_CHANNEL,
                None,
                {"Untagged": (3.0, 4.0)},
            ),
            (
                "custom_channel_filter",
                DateRange(date_from=DATE_FROM, date_to=DATE_TO),
                WebStatsBreakdown.DEVICE_TYPE,
                [SessionPropertyFilter(key="$channel_type", value="Untagged", operator=PropertyOperator.EXACT)],
                UNTAGGED_CHANNEL,
                None,
                {"Desktop": (2.0, 3.0), "Mobile": (1.0, 1.0)},
            ),
            (
                "range_inside_hour_buckets",
                DateRange(date_from="2024-01-01T10:01:00Z", date_to="2024-01-01T11:30:00Z", explicitDate=True),
                WebStatsBreakdown.DEVICE_TYPE,
                [],
                None,
                None,
                {"Desktop": (1.0, 1.0), "Mobile": (1.0, 1.0)},
            ),
            (
                "bounce_duration_override",
                DateRange(date_from=DATE_FROM, date_to=DATE_TO),
                WebStatsBreakdown.DEVICE_TYPE,
                [],
                HogQLQueryModifiers(bounceRateDurationSeconds=60),
                None,
                {"Desktop": (2.0, 3.0), "Mobile": (1.0, 1.0)},
            ),
            (
                "browser_version_filter",
                DateRange(date_from=DATE_FROM, date_to=DATE_TO),
                WebStatsBreakdown.DEVICE_TYPE,
                [EventPropertyFilter(key="$browser_version", value="120", operator=PropertyOperator.EXACT)],
                None,
                None,
                {"Desktop": (1.0, 2.0)},
            ),
            (
                "range_before_retention_floor",
                DateRange(date_from=DATE_FROM, date_to=DATE_TO),
                WebStatsBreakdown.DEVICE_TYPE,
                [],
                None,
                1,
                {},
            ),
        ]
    )
    def test_ineligible_query_matches_live(
        self, _name, date_range, breakdown, properties, modifiers, retention_months, expected_counts
    ):
        def run(web_query_modifiers):
            runner = WebStatsTableQueryRunner(
                team=self.team,
                query=WebStatsTableQuery(
                    dateRange=date_range,
                    properties=properties,
                    breakdownBy=breakdown,
                    limit=100,
                    webQueryModifiers=web_query_modifiers,
                ),
                modifiers=modifiers,
            )
            response = runner.calculate()
            return runner, self._sort_results(response.results)

        if retention_months is not None:
            self.team.event_retention_months = retention_months
            self.team.save()
        with override_settings(EVENTS_DATA_RETENTION_ENFORCED=retention_months is not None):
            opted_in_runner, opted_in = run(OPT_IN)
            _live_runner, live = run(None)
            assert ready_dimensional_job_ids(opted_in_runner, DIMENSIONAL_READ_TABLES) is None

        assert not opted_in_runner.used_preaggregated_tables
        assert opted_in == live
        assert self._counts(opted_in) == expected_counts

    @parameterized.expand(
        [
            ("stats_table", "DimensionalStatsTableQueryBuilder"),
            ("overview", "DimensionalWebOverviewQueryBuilder"),
        ]
    )
    def test_failed_dimensional_read_falls_back_to_live(self, _name, builder_name):
        self._assert_dimensional_failure(builder_name, RuntimeError("dimensional read failed"), falls_back=True)

    @parameterized.expand(
        [
            ("stats_table_at_capacity", "DimensionalStatsTableQueryBuilder", ClickHouseAtCapacity(), LEGACY),
            ("overview_at_capacity", "DimensionalWebOverviewQueryBuilder", ClickHouseAtCapacity(), LEGACY),
            (
                "overview_cancelled",
                "DimensionalWebOverviewQueryBuilder",
                CHQueryErrorQueryWasCancelled("cancelled", code=394, code_name="query_was_cancelled"),
                LEGACY,
            ),
            ("stats_table_timeout_without_v2", "DimensionalStatsTableQueryBuilder", ClickHouseQueryTimeOut(), None),
            ("overview_timeout_without_v2", "DimensionalWebOverviewQueryBuilder", ClickHouseQueryTimeOut(), None),
        ]
    )
    def test_overload_and_cancel_errors_do_not_rerun_live(self, _name, builder_name, error, modifiers):
        self._assert_dimensional_failure(builder_name, error, falls_back=False, modifiers=modifiers)

    @parameterized.expand(
        [
            ("stats_table", "DimensionalStatsTableQueryBuilder"),
            ("overview", "DimensionalWebOverviewQueryBuilder"),
        ]
    )
    def test_timeout_falls_back_to_v2(self, _name, builder_name):
        self._assert_dimensional_failure(builder_name, ClickHouseQueryTimeOut(), falls_back=True, modifiers=LEGACY)

    def _assert_dimensional_failure(
        self,
        builder_name: str,
        error: Exception,
        falls_back: bool,
        modifiers: HogQLQueryModifiers | None = None,
    ) -> None:
        def run(web_query_modifiers):
            if builder_name == "DimensionalStatsTableQueryBuilder":
                stats_runner = WebStatsTableQueryRunner(
                    team=self.team,
                    query=WebStatsTableQuery(
                        dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
                        properties=[],
                        breakdownBy=WebStatsBreakdown.DEVICE_TYPE,
                        limit=100,
                        webQueryModifiers=web_query_modifiers,
                    ),
                    modifiers=modifiers,
                )
                return self._sort_results(stats_runner.calculate().results)
            overview_runner = WebOverviewQueryRunner(
                team=self.team,
                query=WebOverviewQuery(
                    dateRange=DateRange(date_from=DATE_FROM, date_to=DATE_TO),
                    properties=[],
                    webQueryModifiers=web_query_modifiers,
                ),
                modifiers=modifiers,
            )
            return [(item.key, item.value) for item in overview_runner.calculate().results]

        live = run(None)
        with patch(
            f"products.web_analytics.backend.hogql_queries.web_dimensional_read.{builder_name}.get_query",
            side_effect=error,
        ) as failing_query:
            if falls_back:
                assert run(OPT_IN) == live
            else:
                with self.assertRaises(type(error)):
                    run(OPT_IN)

        assert failing_query.called

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
        assert dimensional.preComputedAt is not None
        assert dimensional.preComputeStale is None
        assert [(item.key, item.value) for item in dimensional.results] == [
            (item.key, item.value) for item in v2.results
        ]
        # visitors, views, sessions: user_a has 2 pageviews, user_b and user_c have 1 each.
        assert [item.value for item in dimensional.results[:3]] == [3, 4, 3]
