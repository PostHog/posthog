from datetime import UTC, datetime

from posthog.test.base import BaseTest

from django.core.exceptions import ValidationError

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.tracing.backend.models import TracingAlertConfiguration, TracingAlertEvent


class TestTracingAlertConfiguration(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._team_scope = team_scope(self.team.id, canonical=True)
        self._team_scope.__enter__()
        self.addCleanup(self._team_scope.__exit__, None, None, None)

    def _create_alert(self, **kwargs) -> TracingAlertConfiguration:
        defaults = {"team": self.team, "name": "Test alert", "threshold_count": 10, "created_by": self.user}
        defaults.update(kwargs)
        return TracingAlertConfiguration.objects.create(**defaults)

    def test_defaults(self):
        alert = self._create_alert()
        assert alert.enabled is True
        assert alert.alert_type == TracingAlertConfiguration.AlertType.THRESHOLD
        assert alert.state == TracingAlertConfiguration.State.NOT_FIRING
        assert alert.threshold_operator == TracingAlertConfiguration.ThresholdOperator.ABOVE
        assert alert.window_minutes == 5
        assert alert.check_interval_minutes == 5
        assert alert.evaluation_periods == 1
        assert alert.datapoints_to_alarm == 1
        assert alert.cooldown_minutes == 0
        assert alert.consecutive_failures == 0
        assert alert.filters == {}

    def test_clear_next_check_only_nulls_next_check_at(self):
        alert = self._create_alert(
            state=TracingAlertConfiguration.State.FIRING,
            next_check_at=datetime(2026, 3, 19, 12, 0, tzinfo=UTC),
            consecutive_failures=3,
        )
        updated = alert.clear_next_check()
        alert.save(update_fields=updated)
        alert.refresh_from_db()
        assert alert.next_check_at is None
        assert alert.state == TracingAlertConfiguration.State.FIRING
        assert alert.consecutive_failures == 3
        assert updated == ["next_check_at"]

    def test_to_snapshot_captures_state_machine_inputs(self):
        from products.tracing.backend.alert_state_machine import AlertState

        alert = self._create_alert(
            state=TracingAlertConfiguration.State.FIRING,
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
            check = TracingAlertEvent.objects.create(
                alert=alert, threshold_breached=breached, state_before="not_firing", state_after="not_firing"
            )
            TracingAlertEvent.objects.filter(pk=check.pk).update(created_at=datetime(2026, 3, 19, 12, i, tzinfo=UTC))

        result = alert.get_recent_breaches()
        assert result == (True, True, False)

    def test_get_recent_breaches_excludes_errored_checks(self):
        alert = self._create_alert(evaluation_periods=5)
        for i, (breached, error) in enumerate([(True, None), (False, "timeout"), (False, None)]):
            check = TracingAlertEvent.objects.create(
                alert=alert,
                threshold_breached=breached,
                state_before="not_firing",
                state_after="not_firing",
                error_message=error,
            )
            TracingAlertEvent.objects.filter(pk=check.pk).update(created_at=datetime(2026, 3, 19, 12, i, tzinfo=UTC))

        result = alert.get_recent_breaches()
        assert result == (False, True)

    @parameterized.expand([(k.value, k) for k in TracingAlertEvent.Kind if k != TracingAlertEvent.Kind.CHECK])
    def test_get_recent_breaches_excludes_non_check_kinds(self, _name, non_check_kind):
        # Control-plane rows (resets, snoozes, etc.) must never participate in N-of-M.
        alert = self._create_alert(evaluation_periods=3)
        check = TracingAlertEvent.objects.create(
            alert=alert,
            kind=TracingAlertEvent.Kind.CHECK,
            threshold_breached=True,
            state_before="not_firing",
            state_after="firing",
        )
        TracingAlertEvent.objects.filter(pk=check.pk).update(created_at=datetime(2026, 3, 19, 12, 0, tzinfo=UTC))
        control = TracingAlertEvent.objects.create(
            alert=alert,
            kind=non_check_kind,
            threshold_breached=False,
            state_before="not_firing",
            state_after="not_firing",
        )
        TracingAlertEvent.objects.filter(pk=control.pk).update(created_at=datetime(2026, 3, 19, 12, 1, tzinfo=UTC))

        result = alert.get_recent_breaches()
        assert result == (True,)

    @parameterized.expand(
        [
            ("valid_n_less_than_m", 2, 3),
            ("valid_n_equals_m", 3, 3),
        ]
    )
    def test_clean_accepts_n_of_m(self, _name, datapoints_to_alarm, evaluation_periods):
        alert = self._create_alert(
            datapoints_to_alarm=datapoints_to_alarm,
            evaluation_periods=evaluation_periods,
            filters={"serviceNames": ["ingestion"]},
        )
        alert.full_clean()

    def test_clean_rejects_n_greater_than_m(self):
        alert = self._create_alert(datapoints_to_alarm=3, evaluation_periods=2, filters={"serviceNames": ["ingestion"]})
        with self.assertRaises(ValidationError) as ctx:
            alert.full_clean()
        assert "datapoints_to_alarm cannot exceed evaluation_periods" in str(ctx.exception)
