from datetime import UTC, datetime

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db.models import F

from parameterized import parameterized

from posthog.errors import QueryErrorCategory

from products.logs.backend.alert_check_query import AlertCheckCountResult
from products.logs.backend.alert_state_machine import AlertState, NotificationAction
from products.logs.backend.models import MAX_EVALUATION_PERIODS, LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.temporal.activities import CheckAlertsOutput, _check_alerts_sync, _evaluate_single_alert


def _make_stats() -> dict[str, int]:
    return {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}


class TestCheckAlertsSync(APIBaseTest):
    def _make_alert(self, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "Test Alert",
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 5,
            "filters": {"serviceNames": ["test-service"]},
            "next_check_at": datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    def test_no_alerts_returns_zero_stats(self, mock_query_cls):
        result = _check_alerts_sync()
        assert result == CheckAlertsOutput(alerts_checked=0, alerts_fired=0, alerts_resolved=0, alerts_errored=0)
        mock_query_cls.assert_not_called()

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    def test_skips_disabled_alerts(self, mock_query_cls):
        self._make_alert(enabled=False)
        result = _check_alerts_sync()
        assert result.alerts_checked == 0
        mock_query_cls.assert_not_called()

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    def test_skips_snoozed_alerts(self, mock_query_cls):
        self._make_alert(
            state=LogsAlertConfiguration.State.SNOOZED,
            snooze_until=datetime(2025, 1, 2, 0, 0, 0, tzinfo=UTC),
        )
        result = _check_alerts_sync()
        assert result.alerts_checked == 0

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    def test_skips_broken_alerts(self, mock_query_cls):
        self._make_alert(state=LogsAlertConfiguration.State.BROKEN)
        result = _check_alerts_sync()
        assert result.alerts_checked == 0
        mock_query_cls.assert_not_called()

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    def test_picks_up_due_alert(self, mock_query_cls):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=5, query_duration_ms=100)
        self._make_alert()
        result = _check_alerts_sync()
        assert result.alerts_checked == 1

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    def test_picks_up_null_next_check_at(self, mock_query_cls):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=5, query_duration_ms=100)
        self._make_alert(next_check_at=None)
        result = _check_alerts_sync()
        assert result.alerts_checked == 1

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    def test_skips_future_next_check_at(self, mock_query_cls):
        self._make_alert(next_check_at=datetime(2025, 1, 1, 1, 0, 0, tzinfo=UTC))
        result = _check_alerts_sync()
        assert result.alerts_checked == 0

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    def test_clickhouse_error_records_errored_check(self, mock_query_cls):
        mock_query_cls.return_value.execute.side_effect = RuntimeError("boom")
        self._make_alert()
        result = _check_alerts_sync()
        # ClickHouse error is caught inside _evaluate_single_alert, alert is still "checked"
        assert result.alerts_checked == 1
        assert result.alerts_errored == 1

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities._evaluate_single_alert", side_effect=RuntimeError("unexpected"))
    def test_unexpected_error_increments_errored(self, _mock_evaluate):
        self._make_alert()
        result = _check_alerts_sync()
        # Truly unexpected error caught by outer except — not "checked"
        assert result.alerts_errored == 1
        assert result.alerts_checked == 0

    @parameterized.expand(
        [
            ("with_due_alerts", True, 2),
            ("none_due", False, 0),
        ]
    )
    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.record_alerts_active")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    def test_records_alerts_active_gauge(self, _name, seed_alerts, expected_count, mock_query_cls, mock_record_gauge):
        if seed_alerts:
            mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=5, query_duration_ms=100)
            self._make_alert()
            self._make_alert(name="Second")
            # Disabled and snoozed alerts should not count toward the gauge.
            self._make_alert(name="Disabled", enabled=False)
            self._make_alert(
                name="Snoozed",
                state=LogsAlertConfiguration.State.SNOOZED,
                snooze_until=datetime(2025, 1, 2, 0, 0, 0, tzinfo=UTC),
            )

        _check_alerts_sync()

        mock_record_gauge.assert_called_once_with(expected_count)


class TestEvaluateSingleAlert(APIBaseTest):
    def setUp(self):
        super().setUp()
        # Silence the per-alert metric helpers at class level — they raise outside
        # Temporal context and the try/except in activities.py swallows the first raise,
        # skipping later helpers that individual tests want to assert on.
        for target in (
            "products.logs.backend.temporal.activities.record_check_duration",
            "products.logs.backend.temporal.activities.record_scheduler_lag",
            "products.logs.backend.temporal.activities.increment_checks_total",
            "products.logs.backend.temporal.activities.increment_check_errors",
        ):
            p = patch(target)
            p.start()
            self.addCleanup(p.stop)

    def _make_alert(self, **kwargs) -> LogsAlertConfiguration:
        defaults = {
            "team": self.team,
            "name": "Test Alert",
            "threshold_count": 10,
            "threshold_operator": "above",
            "window_minutes": 5,
            "filters": {"serviceNames": ["test-service"]},
        }
        defaults.update(kwargs)
        return LogsAlertConfiguration.objects.create(**defaults)

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_threshold_breached_transitions_to_firing(self, mock_produce, mock_query_cls):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=50, query_duration_ms=100)
        alert = self._make_alert()
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_single_alert(alert, now, stats)

        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.FIRING
        assert stats["checked"] == 1
        assert stats["fired"] == 1
        mock_produce.assert_called_once()
        assert mock_produce.call_args.kwargs["event"].event == "$logs_alert_firing"

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_threshold_not_breached_stays_not_firing(self, mock_produce, mock_query_cls):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=5, query_duration_ms=100)
        alert = self._make_alert()
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_single_alert(alert, now, stats)

        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING
        assert stats["checked"] == 1
        assert stats["fired"] == 0
        mock_produce.assert_not_called()

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_creates_event_row(self, mock_produce, mock_query_cls):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=50, query_duration_ms=250)
        alert = self._make_alert()
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_single_alert(alert, now, stats)

        check = LogsAlertEvent.objects.get(alert=alert)
        assert check.result_count == 50
        assert check.threshold_breached is True
        assert check.state_before == "not_firing"
        assert check.state_after == "firing"
        assert check.query_duration_ms == 250
        assert check.error_message is None

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_advances_next_check_at(self, mock_produce, mock_query_cls):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=5, query_duration_ms=100)
        alert = self._make_alert(next_check_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC))
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_single_alert(alert, now, stats)

        alert.refresh_from_db()
        assert alert.next_check_at is not None and alert.next_check_at > now

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_inline_cap_trims_oldest_non_event_rows(self, _mock_produce, mock_query_cls):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=5, query_duration_ms=100)
        alert = self._make_alert()

        # Seed MAX_EVALUATION_PERIODS non-event rows (the allowed headroom).
        for _ in range(MAX_EVALUATION_PERIODS):
            LogsAlertEvent.objects.create(
                alert=alert, threshold_breached=False, state_before="not_firing", state_after="not_firing"
            )
        # Seed an event row the activity should never touch.
        errored = LogsAlertEvent.objects.create(
            alert=alert,
            threshold_breached=False,
            state_before="not_firing",
            state_after="not_firing",
            error_message="Old CH timeout",
        )

        _evaluate_single_alert(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats())

        # Cap is MAX_EVALUATION_PERIODS + the new check that was just inserted.
        non_event_count = LogsAlertEvent.objects.filter(
            alert=alert, error_message__isnull=True, state_before=F("state_after")
        ).count()
        assert non_event_count == MAX_EVALUATION_PERIODS
        # The errored row survives the cap — events are retention-managed, not count-managed.
        assert LogsAlertEvent.objects.filter(pk=errored.pk).exists()

    @parameterized.expand([(k.value, k) for k in LogsAlertEvent.Kind if k != LogsAlertEvent.Kind.CHECK])
    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_inline_prune_leaves_non_check_kinds_alone(self, _name, non_check_kind, _mock_produce, mock_query_cls):
        # Control-plane rows are excluded from the prune candidate set by `kind=CHECK`.
        # Without that filter, a hypothetical non-CHECK row with state_before=state_after
        # would match the legacy "non-event" filter and get trimmed along with OK rows.
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=5, query_duration_ms=100)
        alert = self._make_alert()

        for _ in range(MAX_EVALUATION_PERIODS + 5):
            LogsAlertEvent.objects.create(
                alert=alert,
                kind=LogsAlertEvent.Kind.CHECK,
                threshold_breached=False,
                state_before="not_firing",
                state_after="not_firing",
            )
        control = LogsAlertEvent.objects.create(
            alert=alert,
            kind=non_check_kind,
            threshold_breached=False,
            state_before="not_firing",
            state_after="not_firing",
        )

        _evaluate_single_alert(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats())

        assert LogsAlertEvent.objects.filter(pk=control.pk).exists()

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    @patch(
        "products.logs.backend.alert_error_classifier.classify_query_error",
        return_value=QueryErrorCategory.QUERY_PERFORMANCE_ERROR,
    )
    def test_clickhouse_failure_creates_error_event_row(self, _mock_classify, mock_produce, mock_query_cls):
        # Force the classifier to treat this as a performance error so the assertion
        # doesn't depend on whether the raw message hits one of the shared classifier's
        # recognized shapes.
        mock_query_cls.return_value.execute.side_effect = Exception(
            "Code: 160. DB::Exception: Estimated query execution time is too long"
        )
        alert = self._make_alert()
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_single_alert(alert, now, stats)

        check = LogsAlertEvent.objects.get(alert=alert)
        assert check.result_count is None
        assert check.threshold_breached is False
        assert check.error_message == "Query is too expensive. Try narrower filters or a shorter window."
        assert "DB::Exception" not in (check.error_message or "")
        assert stats["errored"] == 1

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_emit_event_uses_team_distinct_id(self, mock_produce, mock_query_cls):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=50, query_duration_ms=100)
        alert = self._make_alert()
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_single_alert(alert, now, stats)

        event = mock_produce.call_args.kwargs["event"]
        assert event.distinct_id == f"team_{self.team.id}"

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_last_notified_at_set_after_kafka_success(self, mock_produce, mock_query_cls):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=50, query_duration_ms=100)
        alert = self._make_alert()
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_single_alert(alert, now, stats)

        alert.refresh_from_db()
        assert alert.last_notified_at == now

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event", side_effect=Exception("Kafka down"))
    @patch("products.logs.backend.temporal.activities.capture_exception")
    def test_last_notified_at_not_set_on_kafka_failure(self, mock_capture, mock_produce, mock_query_cls):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=50, query_duration_ms=100)
        alert = self._make_alert()
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_single_alert(alert, now, stats)

        alert.refresh_from_db()
        assert alert.last_notified_at is None
        mock_capture.assert_called_once()

    @parameterized.expand(
        [
            ("above_breached", "above", 50, True),
            ("above_not_breached", "above", 5, False),
            ("below_breached", "below", 5, True),
            ("below_not_breached", "below", 50, False),
        ]
    )
    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_threshold_operators(self, _name, operator, count, should_fire, mock_produce, mock_query_cls):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=count, query_duration_ms=100)
        alert = self._make_alert(threshold_operator=operator, threshold_count=10)
        stats = {"checked": 0, "fired": 0, "resolved": 0, "errored": 0}
        now = datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC)

        _evaluate_single_alert(alert, now, stats)

        alert.refresh_from_db()
        if should_fire:
            assert alert.state == LogsAlertConfiguration.State.FIRING
            assert stats["fired"] == 1
        else:
            assert alert.state == LogsAlertConfiguration.State.NOT_FIRING
            assert stats["fired"] == 0

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_resolution_emits_resolved_event(self, mock_produce, mock_query_cls):
        alert = self._make_alert(state=LogsAlertConfiguration.State.FIRING)
        # First check breached to create an event row for get_recent_breaches
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=50, query_duration_ms=100)
        _evaluate_single_alert(alert, datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC), _make_stats())
        alert.refresh_from_db()
        mock_produce.reset_mock()

        # Second check not breached — should resolve
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=0, query_duration_ms=100)
        stats = _make_stats()
        _evaluate_single_alert(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), stats)

        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING
        assert stats["resolved"] == 1
        mock_produce.assert_called_once()
        assert mock_produce.call_args.kwargs["event"].event == "$logs_alert_resolved"

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_cooldown_suppresses_notification(self, mock_produce, mock_query_cls):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=50, query_duration_ms=100)
        alert = self._make_alert(
            state=LogsAlertConfiguration.State.FIRING,
            cooldown_minutes=60,
            last_notified_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        stats = _make_stats()
        # 1 minute after last notification, within 60-min cooldown
        _evaluate_single_alert(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), stats)

        alert.refresh_from_db()
        # State transitions still happen, but no notification emitted
        assert alert.state == LogsAlertConfiguration.State.FIRING
        mock_produce.assert_not_called()

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_n_of_m_requires_multiple_breaches_to_fire(self, mock_produce, mock_query_cls):
        alert = self._make_alert(evaluation_periods=3, datapoints_to_alarm=2)

        # First check: breached but 1-of-3 not enough
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=50, query_duration_ms=100)
        _evaluate_single_alert(alert, datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC), _make_stats())
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING

        # Second check: not breached, 1-of-3 still not enough
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=0, query_duration_ms=100)
        _evaluate_single_alert(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats())
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING

        # Third check: breached, now 2-of-3 — should fire
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=50, query_duration_ms=100)
        stats = _make_stats()
        _evaluate_single_alert(alert, datetime(2025, 1, 1, 0, 2, 0, tzinfo=UTC), stats)
        alert.refresh_from_db()
        assert alert.state == LogsAlertConfiguration.State.FIRING
        assert stats["fired"] == 1
        mock_produce.assert_called_once()

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_event_properties_include_logs_url_params(self, mock_produce, mock_query_cls):
        alert = self._make_alert(
            threshold_count=5,
            filters={"severityLevels": ["error"], "serviceNames": ["api-server"]},
        )
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=10, query_duration_ms=50)

        _evaluate_single_alert(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats())

        assert mock_produce.called
        props = mock_produce.call_args.kwargs["event"].properties
        assert "logs_url_params" in props
        assert "severityLevels" in props["logs_url_params"]
        assert "api-server" in props["logs_url_params"]
        assert props["service_names"] == ["api-server"]
        assert props["severity_levels"] == ["error"]
        assert props["triggered_at"] == "2025-01-01T00:01:00+00:00"

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_logs_url_params_includes_absolute_date_range(self, mock_produce, mock_query_cls):
        alert = self._make_alert(
            threshold_count=5,
            window_minutes=10,
            filters={"severityLevels": ["error"]},
        )
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=10, query_duration_ms=50)

        _evaluate_single_alert(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats())

        props = mock_produce.call_args.kwargs["event"].properties
        assert "dateRange" in props["logs_url_params"]
        # Window is 10m, check time is 00:01 — so date_from should be 23:51 (previous day)
        assert "2024-12-31T23%3A51%3A00" in props["logs_url_params"] or "23:51:00" in props["logs_url_params"]
        assert "2025-01-01T00%3A01%3A00" in props["logs_url_params"] or "00:01:00" in props["logs_url_params"]

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_resolution_within_cooldown_suppresses_resolved_event(self, mock_produce, mock_query_cls):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=0, query_duration_ms=100)
        alert = self._make_alert(
            state=LogsAlertConfiguration.State.FIRING,
            cooldown_minutes=60,
            last_notified_at=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        # Create an event row so get_recent_breaches has data
        LogsAlertEvent.objects.create(
            alert=alert,
            result_count=50,
            threshold_breached=True,
            state_before="not_firing",
            state_after="firing",
        )

        stats = _make_stats()
        _evaluate_single_alert(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), stats)

        alert.refresh_from_db()
        # State transitions to NOT_FIRING regardless of cooldown
        assert alert.state == LogsAlertConfiguration.State.NOT_FIRING
        # But notification is suppressed by cooldown
        mock_produce.assert_not_called()

    @parameterized.expand(
        [
            (
                "hits_threshold",
                4,
                LogsAlertConfiguration.State.NOT_FIRING,
                LogsAlertConfiguration.State.BROKEN,
                5,
                1,
            ),
            (
                "below_threshold",
                3,
                LogsAlertConfiguration.State.NOT_FIRING,
                LogsAlertConfiguration.State.ERRORED,
                4,
                0,
            ),
            (
                "already_broken",
                5,
                LogsAlertConfiguration.State.BROKEN,
                LogsAlertConfiguration.State.BROKEN,
                5,
                0,
            ),
        ]
    )
    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_break_on_consecutive_failures(
        self,
        _name,
        initial_failures,
        initial_state,
        expected_state,
        expected_failures,
        expected_events,
        mock_produce,
        mock_query_cls,
    ):
        alert = self._make_alert(
            threshold_count=5,
            consecutive_failures=initial_failures,
            state=initial_state,
        )
        mock_query_cls.return_value.execute.side_effect = Exception(
            "Code: 160. DB::Exception: Estimated query execution time is too long"
        )

        with patch(
            "products.logs.backend.alert_error_classifier.classify_query_error",
            return_value=QueryErrorCategory.QUERY_PERFORMANCE_ERROR,
        ):
            _evaluate_single_alert(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats())

        alert.refresh_from_db()
        assert alert.state == expected_state
        assert alert.consecutive_failures == expected_failures
        auto_disabled_calls = [
            c
            for c in mock_produce.call_args_list
            if c.kwargs.get("event") and c.kwargs["event"].event == "$logs_alert_auto_disabled"
        ]
        assert len(auto_disabled_calls) == expected_events
        if expected_events:
            props = auto_disabled_calls[0].kwargs["event"].properties
            assert props["consecutive_failures"] == expected_failures
            # Auto-disabled event surfaces the classified user message, never the raw CH exception.
            assert props["last_error_message"] == "Query is too expensive. Try narrower filters or a shorter window."
            assert "DB::Exception" not in props["last_error_message"]

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.increment_state_transition")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_state_transition_counter_fires_on_state_change(self, _mock_produce, mock_query_cls, mock_transition):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=50, query_duration_ms=100)
        alert = self._make_alert()

        _evaluate_single_alert(alert, datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats())

        mock_transition.assert_called_once_with(AlertState.NOT_FIRING, AlertState.FIRING)

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.increment_state_transition")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_state_transition_counter_silent_when_state_unchanged(self, _mock_produce, mock_query_cls, mock_transition):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=5, query_duration_ms=100)
        self._make_alert()

        _evaluate_single_alert(
            LogsAlertConfiguration.objects.get(), datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats()
        )

        mock_transition.assert_not_called()

    @parameterized.expand(
        [
            ("fire", 50, LogsAlertConfiguration.State.NOT_FIRING),
            ("resolve", 0, LogsAlertConfiguration.State.FIRING),
        ]
    )
    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.increment_notification_failures")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event", side_effect=Exception("Kafka down"))
    @patch("products.logs.backend.temporal.activities.capture_exception")
    def test_notification_failures_counter(
        self,
        expected_action_name,
        result_count,
        initial_state,
        _mock_capture,
        _mock_produce,
        mock_query_cls,
        mock_notif_failures,
    ):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(
            count=result_count, query_duration_ms=100
        )
        self._make_alert(state=initial_state)

        _evaluate_single_alert(
            LogsAlertConfiguration.objects.get(), datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats()
        )

        mock_notif_failures.assert_called_once_with(NotificationAction(expected_action_name))

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.increment_notification_failures")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_notification_failures_silent_on_success(self, _mock_produce, mock_query_cls, mock_notif_failures):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=50, query_duration_ms=100)
        self._make_alert()

        _evaluate_single_alert(
            LogsAlertConfiguration.objects.get(), datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats()
        )

        mock_notif_failures.assert_not_called()

    @parameterized.expand(
        [
            ("server_busy", QueryErrorCategory.RATE_LIMITED),
            ("query_performance", QueryErrorCategory.QUERY_PERFORMANCE_ERROR),
            ("cancelled", QueryErrorCategory.CANCELLED),
            ("unknown", QueryErrorCategory.ERROR),
        ]
    )
    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.increment_check_errors")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_check_errors_counter_labelled_by_classifier(
        self,
        expected_category,
        classifier_category,
        _mock_produce,
        mock_query_cls,
        mock_check_errors,
    ):
        mock_query_cls.return_value.execute.side_effect = Exception("boom")
        self._make_alert()

        with patch(
            "products.logs.backend.alert_error_classifier.classify_query_error",
            return_value=classifier_category,
        ):
            _evaluate_single_alert(
                LogsAlertConfiguration.objects.get(), datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats()
            )

        mock_check_errors.assert_called_once_with(expected_category)

    @freeze_time("2025-01-01T00:01:00Z")
    @patch("products.logs.backend.temporal.activities.increment_check_errors")
    @patch("products.logs.backend.temporal.activities.AlertCheckQuery")
    @patch("products.logs.backend.temporal.activities.produce_internal_event")
    def test_check_errors_counter_silent_on_success(self, _mock_produce, mock_query_cls, mock_check_errors):
        mock_query_cls.return_value.execute.return_value = AlertCheckCountResult(count=5, query_duration_ms=100)
        self._make_alert()

        _evaluate_single_alert(
            LogsAlertConfiguration.objects.get(), datetime(2025, 1, 1, 0, 1, 0, tzinfo=UTC), _make_stats()
        )

        mock_check_errors.assert_not_called()
