from datetime import UTC, datetime

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import CachedLifecycleQueryResponse, DashboardFilter, EventsNode, IntervalType, LifecycleQuery

from products.product_analytics.backend.hogql_queries.lifecycle.lifecycle_query_runner import LifecycleQueryRunner


class TestLifecycleDashboardFilters(BaseTest):
    def _runner(self) -> LifecycleQueryRunner:
        return LifecycleQueryRunner(
            query=LifecycleQuery(series=[EventsNode(event="$pageview")], interval=IntervalType.DAY),
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


class TestLifecycleSeriesCustomNames(BaseTest):
    @parameterized.expand(
        [
            (
                "patches_all_lifecycle_statuses",
                [
                    {"action": {"order": 0, "custom_name": None}, "status": "new", "data": [1]},
                    {"action": {"order": 0, "custom_name": None}, "status": "returning", "data": [2]},
                    {"action": {"order": 0, "custom_name": None}, "status": "resurrecting", "data": [3]},
                    {"action": {"order": 0, "custom_name": None}, "status": "dormant", "data": [4]},
                ],
                [
                    {"action": {"order": 0, "custom_name": "My Lifecycle"}, "status": "new", "data": [1]},
                    {"action": {"order": 0, "custom_name": "My Lifecycle"}, "status": "returning", "data": [2]},
                    {"action": {"order": 0, "custom_name": "My Lifecycle"}, "status": "resurrecting", "data": [3]},
                    {"action": {"order": 0, "custom_name": "My Lifecycle"}, "status": "dormant", "data": [4]},
                ],
                True,
            ),
            (
                "not_modified_when_lifecycle_names_match",
                [
                    {"action": {"order": 0, "custom_name": "My Lifecycle"}, "status": "new", "data": [1]},
                ],
                [
                    {"action": {"order": 0, "custom_name": "My Lifecycle"}, "status": "new", "data": [1]},
                ],
                False,
            ),
        ]
    )
    def test_apply_lifecycle_custom_names(
        self,
        _name: str,
        cached_results: list,
        expected_results: list,
        expect_modified: bool,
    ):
        query = LifecycleQuery(
            series=[
                EventsNode(event="$pageview", custom_name="My Lifecycle"),
            ]
        )

        runner = LifecycleQueryRunner(query=query, team=self.team)

        cached_response = CachedLifecycleQueryResponse(
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
