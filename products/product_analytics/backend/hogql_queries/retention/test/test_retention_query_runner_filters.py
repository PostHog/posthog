from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import DashboardFilter, IntervalType, RetentionFilter, RetentionQuery

from products.product_analytics.backend.hogql_queries.retention.retention_query_runner import RetentionQueryRunner


class TestRetentionDashboardFilters(BaseTest):
    def _runner(self) -> RetentionQueryRunner:
        return RetentionQueryRunner(query=RetentionQuery(retentionFilter=RetentionFilter()), team=self.team)

    def test_dashboard_interval_override_is_skipped(self) -> None:
        runner = self._runner()

        runner.apply_dashboard_filters(DashboardFilter(interval=IntervalType.WEEK))

        assert not hasattr(runner.query, "interval")

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
