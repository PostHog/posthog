from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from products.logs.backend.alert_check_query import BatchedBucketedResult, BucketedCount
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.temporal.alert_cycle import _evaluate_due_logs_alerts_sync

# The cycle imports the query layer inside its function body to keep Django models
# out of Temporal's workflow sandbox, so patches must target the source module.
_QUERY_MODULE = "products.logs.backend.alert_check_query"
_PERSISTED_FIELDS = (
    "state",
    "consecutive_failures",
    "next_check_at",
    "last_notified_at",
    "snooze_until",
)


class TestLogsAlertSourceCycle(APIBaseTest):
    def _breaching_alert(self) -> LogsAlertConfiguration:
        return LogsAlertConfiguration.objects.create(
            team=self.team,
            name="API errors",
            threshold_count=10,
            threshold_operator="above",
            window_minutes=5,
            filters={},
            next_check_at=datetime.now(UTC) - timedelta(minutes=1),
        )

    def test_a_breaching_alert_previews_a_notification_and_stays_untouched(self) -> None:
        alert = self._breaching_alert()
        before = LogsAlertConfiguration.objects.values(*_PERSISTED_FIELDS).get(id=alert.id)

        with (
            patch(f"{_QUERY_MODULE}.fetch_live_logs_checkpoint", return_value=None),
            patch(f"{_QUERY_MODULE}.BatchedAlertCheckQuery") as query,
        ):
            query.return_value.execute_rolling_checks.return_value = BatchedBucketedResult(
                per_alert={str(alert.id): [BucketedCount(timestamp=datetime.now(UTC), count=500)]},
                query_duration_ms=1,
            )
            evaluation = _evaluate_due_logs_alerts_sync()

        assert [preview.notification for preview in evaluation.previews] == ["fire"]
        assert evaluation.alerts_evaluated == 1

        # The production logs fleet owns this alert's state. A write here would advance its
        # schedule or transition it, and the person watching it would be notified twice.
        assert LogsAlertConfiguration.objects.values(*_PERSISTED_FIELDS).get(id=alert.id) == before
        assert not LogsAlertEvent.objects.filter(alert=alert).exists()
