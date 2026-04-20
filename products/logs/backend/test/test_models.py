from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError

from parameterized import parameterized

from products.logs.backend.models import MAX_EVALUATION_PERIODS, LogsAlertConfiguration, LogsAlertEvent


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

    def test_enabled_save_preserves_state(self):
        # State transitions are the responsibility of the state machine now — a plain
        # model save must not mutate state, not even as a side effect of enabled=False.
        alert = self._create_alert(state=LogsAlertConfiguration.State.FIRING)
        alert.name = "Renamed"
        alert.save()
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.FIRING

    def test_model_save_does_not_touch_state_on_disable(self):
        # Disabling via bare .enabled = False + save() must NOT implicitly flip state —
        # the enable/disable state transition lives in the state machine and is driven
        # by the serializer. This test guards against regression of the old save override.
        alert = self._create_alert(state=LogsAlertConfiguration.State.FIRING)
        alert.enabled = False
        alert.save(update_fields=["enabled"])
        alert.refresh_from_db()
        assert alert.enabled is False
        assert alert.state == LogsAlertConfiguration.State.FIRING

    def test_clear_next_check_only_nulls_next_check_at(self):
        alert = self._create_alert(
            state=LogsAlertConfiguration.State.FIRING,
            next_check_at=datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
            consecutive_failures=3,
        )
        updated = alert.clear_next_check()
        alert.save(update_fields=updated)
        alert.refresh_from_db()
        assert alert.next_check_at is None
        # State + consecutive_failures are untouched — that's the state machine's job.
        assert alert.state == LogsAlertConfiguration.State.FIRING
        assert alert.consecutive_failures == 3
        assert updated == ["next_check_at"]

    def test_to_snapshot_captures_state_machine_inputs(self):
        from products.logs.backend.alert_state_machine import AlertState

        alert = self._create_alert(
            state=LogsAlertConfiguration.State.FIRING,
            consecutive_failures=2,
            evaluation_periods=3,
            datapoints_to_alarm=2,
            cooldown_minutes=15,
        )
        snapshot = alert.to_snapshot()
        assert snapshot.state == AlertState.FIRING
        assert snapshot.consecutive_failures == 2
        assert snapshot.evaluation_periods == 3
        assert snapshot.datapoints_to_alarm == 2
        assert snapshot.cooldown_minutes == 15

    def test_get_recent_breaches_ordering_and_limit(self):
        alert = self._create_alert(evaluation_periods=3)
        for i, breached in enumerate([False, True, False, True, True]):
            check = LogsAlertEvent.objects.create(
                alert=alert,
                threshold_breached=breached,
                state_before="not_firing",
                state_after="not_firing",
            )
            LogsAlertEvent.objects.filter(pk=check.pk).update(created_at=datetime(2026, 3, 19, 12, i, tzinfo=UTC))

        result = alert.get_recent_breaches()
        assert result == (True, True, False)

    def test_get_recent_breaches_excludes_errored_checks(self):
        alert = self._create_alert(evaluation_periods=5)
        for i, (breached, error) in enumerate([(True, None), (False, "timeout"), (False, None)]):
            check = LogsAlertEvent.objects.create(
                alert=alert,
                threshold_breached=breached,
                state_before="not_firing",
                state_after="not_firing",
                error_message=error,
            )
            LogsAlertEvent.objects.filter(pk=check.pk).update(created_at=datetime(2026, 3, 19, 12, i, tzinfo=UTC))

        result = alert.get_recent_breaches()
        assert result == (False, True)

    @parameterized.expand([(k.value, k) for k in LogsAlertEvent.Kind if k != LogsAlertEvent.Kind.CHECK])
    def test_get_recent_breaches_excludes_non_check_kinds(self, _name, non_check_kind):
        # Control-plane rows (resets, snoozes, etc.) must never participate in N-of-M.
        # A non-CHECK row with threshold_breached=False would otherwise inject a spurious
        # "not-breaching" data point into the evaluator's window.
        alert = self._create_alert(evaluation_periods=3)
        check = LogsAlertEvent.objects.create(
            alert=alert,
            kind=LogsAlertEvent.Kind.CHECK,
            threshold_breached=True,
            state_before="not_firing",
            state_after="firing",
        )
        LogsAlertEvent.objects.filter(pk=check.pk).update(created_at=datetime(2026, 3, 19, 12, 0, tzinfo=UTC))
        control = LogsAlertEvent.objects.create(
            alert=alert,
            kind=non_check_kind,
            threshold_breached=False,
            state_before="not_firing",
            state_after="not_firing",
        )
        LogsAlertEvent.objects.filter(pk=control.pk).update(created_at=datetime(2026, 3, 19, 12, 1, tzinfo=UTC))

        result = alert.get_recent_breaches()
        assert result == (True,)

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


class TestLogsAlertEvent(BaseTest):
    def _create_alert(self, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "Test alert",
            "threshold_count": 10,
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    def _create_check(self, alert: LogsAlertConfiguration, **kwargs) -> LogsAlertEvent:
        defaults = {
            "alert": alert,
            "threshold_breached": False,
            "state_before": "not_firing",
            "state_after": "not_firing",
        }
        defaults.update(kwargs)
        return LogsAlertEvent.objects.create(**defaults)

    @freeze_time("2026-03-09T12:00:00Z")
    def test_clean_up_old_events_prunes_rows_older_than_event_retention(self):
        alert = self._create_alert()
        old_errored = self._create_check(alert, error_message="CH timeout")
        recent_transition = self._create_check(
            alert, state_before="not_firing", state_after="firing", threshold_breached=True
        )
        LogsAlertEvent.objects.filter(pk=old_errored.pk).update(
            created_at=datetime.now(UTC) - timedelta(days=LogsAlertEvent.EVENT_RETENTION_DAYS + 1)
        )

        deleted = LogsAlertEvent.clean_up_old_events()

        assert deleted == 1
        assert not LogsAlertEvent.objects.filter(pk=old_errored.pk).exists()
        assert LogsAlertEvent.objects.filter(pk=recent_transition.pk).exists()

    @freeze_time("2026-03-09T12:00:00Z")
    def test_clean_up_old_events_does_not_prune_non_event_rows(self):
        # Non-event rows are the activity's problem (inline cap). If a stale OK row sits
        # in the table, clean_up_old_events should leave it alone — the activity will
        # trim it on the next tick.
        alert = self._create_alert()
        for _ in range(MAX_EVALUATION_PERIODS + 5):
            self._create_check(alert)

        deleted = LogsAlertEvent.clean_up_old_events()

        assert deleted == 0
        assert LogsAlertEvent.objects.filter(alert=alert).count() == MAX_EVALUATION_PERIODS + 5

    def test_cascade_delete_with_alert(self):
        alert = self._create_alert()
        self._create_check(alert)
        self._create_check(alert)

        alert.delete()

        assert LogsAlertEvent.objects.count() == 0
