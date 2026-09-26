from datetime import UTC, datetime

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import (
    CachedFunnelsQueryResponse,
    CompareFilter,
    DashboardFilter,
    DateRange,
    EventsNode,
    FunnelsQuery,
    IntervalType,
)

from products.product_analytics.backend.hogql_queries.funnels.funnels_query_runner import FunnelsQueryRunner


class TestFunnelsDashboardFilters(BaseTest):
    def _runner(self, date_from: str | None = None, compare_filter: CompareFilter | None = None) -> FunnelsQueryRunner:
        return FunnelsQueryRunner(
            query=FunnelsQuery(
                series=[EventsNode(event="$pageview")],
                interval=IntervalType.DAY,
                dateRange=DateRange(date_from=date_from) if date_from else None,
                compareFilter=compare_filter,
            ),
            team=self.team,
        )

    @parameterized.expand(
        [
            ("override_written_onto_query", IntervalType.WEEK, IntervalType.WEEK),
            ("absent_override_leaves_query_untouched", None, IntervalType.DAY),
        ]
    )
    def test_dashboard_interval_override(
        self, _name: str, dashboard_interval: IntervalType | None, expected: IntervalType
    ) -> None:
        runner = self._runner()

        runner.apply_dashboard_filters(DashboardFilter(interval=dashboard_interval))

        assert runner.query.interval == expected

    @parameterized.expand(
        [
            ("override_forces_on", None, True, True),
            ("override_forces_off", True, False, False),
            ("absent_override_leaves_query_untouched", True, None, True),
        ]
    )
    def test_dashboard_test_accounts_override(
        self, _name: str, initial: bool | None, dashboard_filter: bool | None, expected: bool
    ) -> None:
        runner = self._runner()
        if initial is not None:
            runner.query.filterTestAccounts = initial

        runner.apply_dashboard_filters(DashboardFilter(filterTestAccounts=dashboard_filter))

        assert runner.query.filterTestAccounts is expected

    def test_dashboard_compare_filter_override(self) -> None:
        runner = self._runner()

        runner.apply_dashboard_filters(DashboardFilter(compareFilter=CompareFilter(compare=True, compare_to="-4w")))

        assert runner.query.compareFilter == CompareFilter(compare=True, compare_to="-4w")

    @parameterized.expand(
        [
            ("compare_set_on_construction", "all", CompareFilter(compare=True), None),
            ("compare_arrives_via_override", "all", None, CompareFilter(compare=True)),
            ("compare_set_on_construction_via_date_override", "-14d", CompareFilter(compare=True), None),
        ]
    )
    def test_dashboard_compare_filter_is_stripped_for_all_time_range(
        self,
        _name: str,
        query_date_from: str,
        construction_compare_filter: CompareFilter | None,
        override_compare_filter: CompareFilter | None,
    ) -> None:
        runner = self._runner(date_from=query_date_from, compare_filter=construction_compare_filter)
        dashboard_date_from = "all" if query_date_from != "all" else None

        runner.apply_dashboard_filters(
            DashboardFilter(date_from=dashboard_date_from, compareFilter=override_compare_filter)
        )

        assert runner.query.dateRange is not None
        assert runner.query.dateRange.date_from == "all"
        assert runner.query.compareFilter == CompareFilter(compare=False)


class TestFunnelsSeriesCustomNames(BaseTest):
    @parameterized.expand(
        [
            (
                "patches_funnel_steps_without_breakdown",
                [
                    {"order": 0, "custom_name": "Old Step 1", "count": 100},
                    {"order": 1, "custom_name": "Old Step 2", "count": 50},
                ],
                [
                    {"order": 0, "custom_name": "Step 1 Renamed", "count": 100},
                    {"order": 1, "custom_name": "Step 2 Renamed", "count": 50},
                ],
                True,
            ),
            (
                "patches_funnel_steps_with_breakdown",
                [
                    [
                        {"order": 0, "custom_name": None, "count": 100, "breakdown": "Chrome"},
                        {"order": 1, "custom_name": None, "count": 50, "breakdown": "Chrome"},
                    ],
                    [
                        {"order": 0, "custom_name": None, "count": 80, "breakdown": "Firefox"},
                        {"order": 1, "custom_name": None, "count": 40, "breakdown": "Firefox"},
                    ],
                ],
                [
                    [
                        {"order": 0, "custom_name": "Step 1 Renamed", "count": 100, "breakdown": "Chrome"},
                        {"order": 1, "custom_name": "Step 2 Renamed", "count": 50, "breakdown": "Chrome"},
                    ],
                    [
                        {"order": 0, "custom_name": "Step 1 Renamed", "count": 80, "breakdown": "Firefox"},
                        {"order": 1, "custom_name": "Step 2 Renamed", "count": 40, "breakdown": "Firefox"},
                    ],
                ],
                True,
            ),
            (
                "not_modified_when_names_match",
                [
                    {"order": 0, "custom_name": "Step 1 Renamed", "count": 100},
                    {"order": 1, "custom_name": "Step 2 Renamed", "count": 50},
                ],
                [
                    {"order": 0, "custom_name": "Step 1 Renamed", "count": 100},
                    {"order": 1, "custom_name": "Step 2 Renamed", "count": 50},
                ],
                False,
            ),
        ]
    )
    def test_apply_funnels_custom_names(
        self,
        _name: str,
        cached_results: list,
        expected_results: list,
        expect_modified: bool,
    ):
        query = FunnelsQuery(
            series=[
                EventsNode(event="step1", custom_name="Step 1 Renamed"),
                EventsNode(event="step2", custom_name="Step 2 Renamed"),
            ]
        )

        runner = FunnelsQueryRunner(query=query, team=self.team)

        cached_response = CachedFunnelsQueryResponse(
            results=cached_results,
            is_cached=True,
            last_refresh=datetime.now(UTC),
            next_allowed_client_refresh=datetime.now(UTC),
            cache_key="test_key",
            timezone="UTC",
        )

        patched_response, was_modified = runner.apply_series_custom_names(cached_response)

        self.assertEqual(patched_response.results, expected_results)
        self.assertEqual(was_modified, expect_modified)
