from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.logs.backend.alert_check_query import BatchedBucketedResult, BucketedCount
from products.logs.backend.alert_source_cycle import evaluate_due_logs_alerts
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent

_MODULE = "products.logs.backend.alert_source_cycle"
_PERSISTED_FIELDS = (
    "state",
    "consecutive_failures",
    "next_check_at",
    "last_notified_at",
    "snooze_until",
)


class TestLogsAlertSourceCycle(APIBaseTest):
    def _breaching_alert(self, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "API errors",
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 5,
            "filters": {},
            "next_check_at": datetime.now(UTC) - timedelta(minutes=1),
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    def _run(
        self,
        *alerts: LogsAlertConfiguration,
        now: datetime | None = None,
        failing: tuple[LogsAlertConfiguration, ...] = (),
    ):
        failing_ids = {str(alert.id) for alert in failing}

        def _build_query(**kwargs) -> MagicMock:
            cohort_ids = [str(alert.id) for alert in kwargs["alerts"]]
            query = MagicMock()
            if failing_ids.intersection(cohort_ids):
                query.execute_rolling_checks.side_effect = Exception("ClickHouse rejected the query")
            else:
                query.execute_rolling_checks.return_value = BatchedBucketedResult(
                    per_alert={
                        alert_id: [BucketedCount(timestamp=datetime.now(UTC), count=500)] for alert_id in cohort_ids
                    },
                    query_duration_ms=1,
                )
            return query

        with (
            patch(f"{_MODULE}.fetch_live_logs_checkpoint", return_value=None),
            patch(f"{_MODULE}.BatchedAlertCheckQuery", side_effect=_build_query) as query,
        ):
            return evaluate_due_logs_alerts(now or datetime.now(UTC)), query

    def test_a_breaching_alert_previews_a_notification_and_stays_untouched(self) -> None:
        alert = self._breaching_alert()
        before = LogsAlertConfiguration.objects.values(*_PERSISTED_FIELDS).get(id=alert.id)

        previews, _ = self._run(alert)

        assert [preview.notification for preview in previews] == ["fire"]
        # The production logs fleet owns this alert's state. A write here would advance its
        # schedule or transition it, and the person watching it would be notified twice.
        assert LogsAlertConfiguration.objects.values(*_PERSISTED_FIELDS).get(id=alert.id) == before
        assert not LogsAlertEvent.objects.filter(alert=alert).exists()

    @parameterized.expand([("single_period", 1, 5), ("three_periods", 3, 25)])
    def test_the_scanned_range_covers_every_rolling_window(
        self, _name: str, evaluation_periods: int, expected_lookback_minutes: int
    ) -> None:
        alert = self._breaching_alert(evaluation_periods=evaluation_periods, check_interval_minutes=10)

        _, query = self._run(alert)

        kwargs = query.call_args.kwargs
        assert kwargs["date_to"] - kwargs["date_from"] == timedelta(minutes=expected_lookback_minutes)

    def test_the_evaluation_key_comes_from_the_tick_occasion_not_the_clock(self) -> None:
        # A retried attempt must select the same windows and keys as the first, so the
        # occasion is passed in rather than read from the clock.
        occasion = datetime(2026, 9, 15, 18, 31, tzinfo=UTC)
        alert = self._breaching_alert(next_check_at=None)

        previews, _ = self._run(alert, now=occasion)

        assert [preview.evaluation_key for preview in previews] == [f"{alert.id}:window:{occasion.isoformat()}"]

    @parameterized.expand(
        [
            ("inside_the_blocked_window", {"blocked_windows": [{"start": "00:00", "end": "06:00"}]}, []),
            ("outside_the_blocked_window", {"blocked_windows": [{"start": "12:00", "end": "18:00"}]}, ["fire"]),
        ]
    )
    def test_an_alert_inside_its_quiet_hours_is_not_previewed(
        self, _name: str, schedule_restriction: dict, expected_notifications: list[str]
    ) -> None:
        # Production reschedules a restricted alert past the window instead of evaluating
        # it, so previewing one here would name a delivery production never makes.
        occasion = datetime(2026, 9, 15, 3, 0, tzinfo=UTC)
        alert = self._breaching_alert(
            next_check_at=occasion - timedelta(minutes=1), schedule_restriction=schedule_restriction
        )

        previews, _ = self._run(alert, now=occasion)

        assert [preview.notification for preview in previews] == expected_notifications

    def test_a_failed_cohort_query_leaves_the_other_cohorts_evaluated(self) -> None:
        # Two window lengths make two cohorts, so each one gets its own ClickHouse query.
        due_at = datetime.now(UTC) - timedelta(minutes=1)
        failing = self._breaching_alert(name="Slow service", window_minutes=5, next_check_at=due_at)
        healthy = self._breaching_alert(name="Checkout errors", window_minutes=7, next_check_at=due_at)

        previews, _ = self._run(failing, healthy, failing=(failing,))

        assert [preview.alert_id for preview in previews] == [str(healthy.id)]
