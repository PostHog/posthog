from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import DashboardFilter, EventsNode, IntervalType, LifecycleQuery

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
