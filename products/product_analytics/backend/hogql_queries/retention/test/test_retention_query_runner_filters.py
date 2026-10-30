from datetime import datetime

import time_machine
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import DashboardFilter, DateRange, IntervalType, RetentionFilter, RetentionQuery

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


class TestRetentionExcludeIncompletePeriods(BaseTest):
    @parameterized.expand(
        [
            ("calendar_dates_clip_the_current_day", "strict_calendar_dates", True),
            ("rolling_windows_ignore_the_exclusion", "24_hour_windows", False),
        ]
    )
    @time_machine.travel("2024-01-10T12:00:00Z", tick=False)
    def test_exclude_incomplete_periods(self, _name: str, time_window_mode: str, clipped: bool) -> None:
        def date_to(exclude: bool) -> datetime:
            query = RetentionQuery(
                retentionFilter=RetentionFilter(timeWindowMode=time_window_mode),
                dateRange=DateRange(date_from="-7d", excludeIncompletePeriods=exclude),
            )
            return RetentionQueryRunner(query=query, team=self.team).query_date_range.date_to()

        assert (date_to(True) < date_to(False)) is clipped
