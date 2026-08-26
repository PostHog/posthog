import uuid
from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.tracing.backend.alert_check_query import BucketedCount
from products.tracing.backend.models import TracingAlertConfiguration, TracingAlertEvent
from products.tracing.backend.temporal.activities import (
    _derive_breaches,
    _discover_due_alerts_sync,
    _evaluate_dispatch_and_save_one_alert,
)


def _bucket_counts_for(counts: list[int]) -> list[BucketedCount]:
    base = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    return [BucketedCount(timestamp=base + timedelta(minutes=i * 5), count=c) for i, c in enumerate(counts)]


def _mock_buckets(mock_query_cls: MagicMock, counts: list[int]) -> None:
    """Set AlertCheckQuery().execute_rolling_checks to return `counts` (oldest-first)."""
    mock_query_cls.return_value.execute_rolling_checks.return_value = _bucket_counts_for(counts)


class TestDeriveBreaches:
    @parameterized.expand(
        [
            ("above_breached", [50], 10, "above", 1, (True,)),
            ("above_not_breached", [5], 10, "above", 1, (False,)),
            ("below_breached", [5], 10, "below", 1, (True,)),
            # CH omits empty buckets — the result must be padded to `evaluation_periods`.
            ("pads_missing_buckets_above", [50], 10, "above", 3, (True, False, False)),
            ("pads_missing_buckets_below", [5], 10, "below", 3, (True, True, True)),
        ]
    )
    def test_derive_breaches(self, _name, counts, threshold, operator, evaluation_periods, expected):
        buckets = _bucket_counts_for(counts)
        assert _derive_breaches(buckets, threshold, operator, evaluation_periods) == expected


class TestDiscoverDueAlerts(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        scope = team_scope(self.team.id, canonical=True)
        scope.__enter__()
        self.addCleanup(scope.__exit__, None, None, None)

    def _create_alert(self, **kwargs) -> TracingAlertConfiguration:
        defaults = {"team": self.team, "name": "Test alert", "threshold_count": 10}
        defaults.update(kwargs)
        return TracingAlertConfiguration.objects.create(**defaults)

    @freeze_time("2025-01-01T00:00:00Z")
    def test_discovers_due_and_excludes_not_due(self):
        due = self._create_alert(next_check_at=datetime(2024, 12, 31, tzinfo=UTC))
        never_checked = self._create_alert(next_check_at=None)
        self._create_alert(next_check_at=datetime(2025, 1, 2, tzinfo=UTC))  # not due yet
        self._create_alert(enabled=False, next_check_at=datetime(2024, 12, 31, tzinfo=UTC))
        self._create_alert(
            state=TracingAlertConfiguration.State.BROKEN, next_check_at=datetime(2024, 12, 31, tzinfo=UTC)
        )
        self._create_alert(
            state=TracingAlertConfiguration.State.SNOOZED,
            next_check_at=datetime(2024, 12, 31, tzinfo=UTC),
            snooze_until=datetime(2025, 1, 5, tzinfo=UTC),
        )

        output = _discover_due_alerts_sync()

        assert set(output.alert_ids) == {str(due.id), str(never_checked.id)}


class TestEvaluateDispatchAndSaveOneAlert(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        scope = team_scope(self.team.id, canonical=True)
        scope.__enter__()
        self.addCleanup(scope.__exit__, None, None, None)

    def _create_alert(self, **kwargs) -> TracingAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "Test alert",
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 5,
            "filters": {"serviceNames": ["web"]},
        }
        defaults.update(kwargs)
        return TracingAlertConfiguration.objects.create(**defaults)

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.tracing.backend.temporal.activities.AlertCheckQuery")
    @patch("products.alerts.backend.destinations.produce_internal_event")
    def test_threshold_breached_transitions_to_firing(self, mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [50])
        alert = self._create_alert()
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        outcome_kind = _evaluate_dispatch_and_save_one_alert(str(alert.id), now)

        alert.refresh_from_db()
        assert outcome_kind == "fired"
        assert alert.state == TracingAlertConfiguration.State.FIRING
        mock_produce.assert_called_once()
        assert mock_produce.call_args.kwargs["event"].event == "$tracing_alert_firing"

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.tracing.backend.temporal.activities.AlertCheckQuery")
    @patch("products.alerts.backend.destinations.produce_internal_event")
    def test_threshold_not_breached_stays_not_firing(self, mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [5])
        alert = self._create_alert()
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        outcome_kind = _evaluate_dispatch_and_save_one_alert(str(alert.id), now)

        alert.refresh_from_db()
        assert outcome_kind == "unchanged"
        assert alert.state == TracingAlertConfiguration.State.NOT_FIRING
        mock_produce.assert_not_called()

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.tracing.backend.temporal.activities.AlertCheckQuery")
    @patch("products.alerts.backend.destinations.produce_internal_event")
    def test_creates_event_row_on_state_change(self, mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [50])
        alert = self._create_alert()
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_dispatch_and_save_one_alert(str(alert.id), now)

        event = TracingAlertEvent.objects.get(alert=alert)
        assert event.result_count == 50
        assert event.threshold_breached is True
        assert event.state_before == "not_firing"
        assert event.state_after == "firing"

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.tracing.backend.temporal.activities.AlertCheckQuery")
    @patch("products.alerts.backend.destinations.produce_internal_event")
    def test_steady_state_writes_no_event(self, _mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [5])
        alert = self._create_alert()

        _evaluate_dispatch_and_save_one_alert(str(alert.id), datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC))

        assert TracingAlertEvent.objects.filter(alert=alert).count() == 0

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.tracing.backend.temporal.activities.AlertCheckQuery")
    @patch("products.alerts.backend.destinations.produce_internal_event")
    def test_advances_next_check_at(self, _mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [5])
        alert = self._create_alert(next_check_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC))
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_dispatch_and_save_one_alert(str(alert.id), now)

        alert.refresh_from_db()
        assert alert.next_check_at is not None and alert.next_check_at > now

    @freeze_time("2025-01-01T21:58:00Z")
    @patch("products.tracing.backend.temporal.activities.AlertCheckQuery")
    @patch("products.alerts.backend.destinations.produce_internal_event")
    def test_advances_next_check_at_past_quiet_hours(self, _mock_produce, mock_query_cls):
        # `now` (21:58) is not itself blocked, so the check runs normally — but the
        # cadence-advanced next_check_at (21:58 + 5min default) lands inside the
        # window and must be pushed past it.
        _mock_buckets(mock_query_cls, [5])  # below threshold → stays not_firing
        alert = self._create_alert(
            next_check_at=datetime(2025, 1, 1, 21, 55, tzinfo=UTC),
            schedule_restriction={"blocked_windows": [{"start": "22:00", "end": "07:00"}]},
        )
        now = datetime(2025, 1, 1, 21, 58, tzinfo=UTC)

        outcome_kind = _evaluate_dispatch_and_save_one_alert(str(alert.id), now)

        alert.refresh_from_db()
        assert outcome_kind == "unchanged"
        assert alert.next_check_at == datetime(2025, 1, 2, 7, 0, tzinfo=UTC)

    @freeze_time("2025-01-01T22:05:00Z")
    @patch("products.tracing.backend.temporal.activities.AlertCheckQuery")
    @patch("products.alerts.backend.destinations.produce_internal_event")
    def test_check_suppressed_while_currently_in_quiet_hours(self, mock_produce, mock_query_cls):
        # `now` (22:05) IS inside the blocked window — v1 tracing enforces quiet
        # hours at dispatch time (unlike logs' discovery-time pre-filter), so the
        # ClickHouse query still runs, but the outcome must not be dispatched or
        # persisted, and the alert gets rescheduled past the window.
        _mock_buckets(mock_query_cls, [50])  # would otherwise fire
        alert = self._create_alert(
            next_check_at=datetime(2025, 1, 1, 22, 0, tzinfo=UTC),
            schedule_restriction={"blocked_windows": [{"start": "22:00", "end": "07:00"}]},
        )
        now = datetime(2025, 1, 1, 22, 5, tzinfo=UTC)

        outcome_kind = _evaluate_dispatch_and_save_one_alert(str(alert.id), now)

        alert.refresh_from_db()
        assert outcome_kind == "suppressed"
        assert alert.next_check_at is not None and alert.next_check_at > now
        assert alert.state == TracingAlertConfiguration.State.NOT_FIRING
        mock_produce.assert_not_called()

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.tracing.backend.temporal.activities.AlertCheckQuery")
    @patch("products.alerts.backend.destinations.produce_internal_event", side_effect=Exception("Kafka down"))
    def test_notification_enqueue_failure_does_not_advance_last_notified_at(self, _mock_produce, mock_query_cls):
        _mock_buckets(mock_query_cls, [50])
        alert = self._create_alert()
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        outcome_kind = _evaluate_dispatch_and_save_one_alert(str(alert.id), now)

        alert.refresh_from_db()
        # State still advances (the check itself succeeded) but delivery is unconfirmed,
        # so last_notified_at must not be set — the next cycle's cooldown math would
        # otherwise treat an undelivered notification as sent.
        assert outcome_kind == "fired"
        assert alert.state == TracingAlertConfiguration.State.FIRING
        assert alert.last_notified_at is None

    def test_missing_alert_raises_does_not_exist(self):
        with self.assertRaises(TracingAlertConfiguration.DoesNotExist):
            _evaluate_dispatch_and_save_one_alert(str(uuid.uuid4()), datetime.now(UTC))
