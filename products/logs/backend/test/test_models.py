from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError

from products.logs.backend.models import MAX_EVALUATION_PERIODS, LogsAlertCheck, LogsAlertConfiguration


class TestLogsAlertConfiguration(BaseTest):
    def _create_alert(self, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "Test alert",
            "threshold_count": 10,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    def test_defaults(self):
        alert = self._create_alert()
        assert alert.enabled is True
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING
        assert alert.threshold_operator == LogsAlertConfiguration.ThresholdOperator.ABOVE
        assert alert.window_minutes == 5
        assert alert.check_interval_minutes == 1
        assert alert.evaluation_periods == 1
        assert alert.datapoints_to_alarm == 1
        assert alert.cooldown_minutes == 0
        assert alert.consecutive_failures == 0
        assert alert.filters == {}

    def test_disable_resets_state_to_not_firing(self):
        alert = self._create_alert(state=LogsAlertConfiguration.State.FIRING)
        alert.enabled = False
        alert.save()
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING

    def test_disable_with_update_fields_includes_state(self):
        alert = self._create_alert(state=LogsAlertConfiguration.State.FIRING)
        alert.enabled = False
        alert.save(update_fields=["enabled"])
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING

    def test_disable_with_update_fields_tuple(self):
        alert = self._create_alert(state=LogsAlertConfiguration.State.FIRING)
        alert.enabled = False
        alert.save(update_fields=("enabled",))
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING

    def test_enabled_save_preserves_state(self):
        alert = self._create_alert(state=LogsAlertConfiguration.State.FIRING)
        alert.name = "Renamed"
        alert.save()
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.FIRING

    def test_mark_for_recheck_resets_state(self):
        alert = self._create_alert(
            state=LogsAlertConfiguration.State.FIRING,
            next_check_at=datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
            consecutive_failures=3,
        )
        updated = alert.mark_for_recheck(reset_state=True)
        alert.save(update_fields=updated)
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING
        assert alert.next_check_at is None
        assert alert.consecutive_failures == 0
        assert "state" in updated
        assert "consecutive_failures" in updated
        assert "next_check_at" in updated

    def test_mark_for_recheck_preserves_state(self):
        alert = self._create_alert(
            state=LogsAlertConfiguration.State.FIRING,
            next_check_at=datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
        )
        updated = alert.mark_for_recheck(reset_state=False)
        alert.save(update_fields=updated)
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.FIRING
        assert alert.next_check_at is None
        assert "state" not in updated

    def test_get_recent_breaches_ordering_and_limit(self):
        alert = self._create_alert(evaluation_periods=3)
        for i, breached in enumerate([False, True, False, True, True]):
            check = LogsAlertCheck.objects.create(
                alert=alert,
                threshold_breached=breached,
                state_before="not_firing",
                state_after="not_firing",
            )
            LogsAlertCheck.objects.filter(pk=check.pk).update(created_at=datetime(2026, 3, 19, 12, i, tzinfo=UTC))

        result = alert.get_recent_breaches()
        assert result == (True, True, False)

    def test_get_recent_breaches_excludes_errored_checks(self):
        alert = self._create_alert(evaluation_periods=5)
        for i, (breached, error) in enumerate([(True, None), (False, "timeout"), (False, None)]):
            check = LogsAlertCheck.objects.create(
                alert=alert,
                threshold_breached=breached,
                state_before="not_firing",
                state_after="not_firing",
                error_message=error,
            )
            LogsAlertCheck.objects.filter(pk=check.pk).update(created_at=datetime(2026, 3, 19, 12, i, tzinfo=UTC))

        result = alert.get_recent_breaches()
        assert result == (False, True)

    def test_clean_valid_n_of_m(self):
        alert = self._create_alert(datapoints_to_alarm=2, evaluation_periods=3, filters={"severityLevels": ["error"]})
        alert.full_clean()

    def test_clean_equal_n_and_m(self):
        alert = self._create_alert(datapoints_to_alarm=3, evaluation_periods=3, filters={"severityLevels": ["error"]})
        alert.full_clean()

    def test_clean_rejects_n_greater_than_m(self):
        alert = self._create_alert(datapoints_to_alarm=3, evaluation_periods=2, filters={"severityLevels": ["error"]})
        with self.assertRaises(ValidationError) as ctx:
            alert.full_clean()
        assert "datapoints_to_alarm cannot exceed evaluation_periods" in str(ctx.exception)


class TestLogsAlertCheck(BaseTest):
    def _create_alert(self, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "Test alert",
            "threshold_count": 10,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    def _create_check(self, alert: LogsAlertConfiguration, **kwargs) -> LogsAlertCheck:
        defaults = {
            "alert": alert,
            "threshold_breached": False,
            "state_before": "not_firing",
            "state_after": "not_firing",
        }
        defaults.update(kwargs)
        return LogsAlertCheck.objects.create(**defaults)

    @freeze_time("2026-03-09T12:00:00Z")
    def test_clean_up_old_checks_prunes_rows_older_than_event_retention(self):
        alert = self._create_alert()
        old_errored = self._create_check(alert, error_message="CH timeout")
        recent_transition = self._create_check(
            alert, state_before="not_firing", state_after="firing", threshold_breached=True
        )
        LogsAlertCheck.objects.filter(pk=old_errored.pk).update(
            created_at=datetime.now(UTC) - timedelta(days=LogsAlertCheck.EVENT_RETENTION_DAYS + 1)
        )

        deleted = LogsAlertCheck.clean_up_old_checks()

        assert deleted == 1
        assert not LogsAlertCheck.objects.filter(pk=old_errored.pk).exists()
        assert LogsAlertCheck.objects.filter(pk=recent_transition.pk).exists()

    @freeze_time("2026-03-09T12:00:00Z")
    def test_clean_up_old_checks_does_not_prune_non_event_rows(self):
        # Non-event rows are the activity's problem (inline cap). If a stale OK row sits
        # in the table, clean_up_old_checks should leave it alone — the activity will
        # trim it on the next tick.
        alert = self._create_alert()
        for _ in range(MAX_EVALUATION_PERIODS + 5):
            self._create_check(alert)

        deleted = LogsAlertCheck.clean_up_old_checks()

        assert deleted == 0
        assert LogsAlertCheck.objects.filter(alert=alert).count() == MAX_EVALUATION_PERIODS + 5

    def test_cascade_delete_with_alert(self):
        alert = self._create_alert()
        self._create_check(alert)
        self._create_check(alert)

        alert.delete()

        assert LogsAlertCheck.objects.count() == 0
