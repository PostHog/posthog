import datetime as dt

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

from products.logs.backend.alert_state_machine import AlertState, NotificationAction
from products.logs.backend.temporal.metrics import (
    ALERTING_ACTIVITY_TYPES,
    AlertOutcome,
    ExecutionTimeRecorder,
    LogsAlertingMetricsInterceptor,
    increment_check_errors,
    increment_checks_total,
    increment_notification_failures,
    increment_state_transition,
    record_alerts_active,
    record_check_duration,
    record_schedule_to_start_latency,
    record_scheduler_lag,
)


class TestLogsAlertingMetricsInterceptor:
    def test_task_queue_matches_settings(self):
        assert LogsAlertingMetricsInterceptor.task_queue == settings.LOGS_ALERTING_TASK_QUEUE

    def test_creates_activity_interceptor(self):
        interceptor = LogsAlertingMetricsInterceptor()
        mock_next = MagicMock()
        result = interceptor.intercept_activity(mock_next)
        assert result is not None


class TestActivityTypes:
    def test_alerting_activity_types(self):
        assert ALERTING_ACTIVITY_TYPES == frozenset({"check_alerts_activity"})


class TestIncrementChecksTotal:
    @pytest.mark.parametrize("outcome", ["ok", "fired", "resolved", "errored"])
    @patch("products.logs.backend.temporal.metrics.get_metric_meter")
    def test_increments_counter_with_outcome(self, mock_get_meter: MagicMock, outcome: AlertOutcome):
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter
        mock_get_meter.return_value = mock_meter

        increment_checks_total(outcome)

        mock_get_meter.assert_called_once_with({"outcome": outcome})
        mock_counter.add.assert_called_once_with(1)


class TestIncrementCheckErrors:
    @pytest.mark.parametrize("category", ["server_busy", "query_performance", "invalid_query", "cancelled", "unknown"])
    @patch("products.logs.backend.temporal.metrics.get_metric_meter")
    def test_increments_counter_with_category(self, mock_get_meter: MagicMock, category):
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter
        mock_get_meter.return_value = mock_meter

        increment_check_errors(category)

        mock_get_meter.assert_called_once_with({"category": category})
        (name, _description), _ = mock_meter.create_counter.call_args
        assert name == "logs_alerting_check_errors_total"
        mock_counter.add.assert_called_once_with(1)


class TestIncrementNotificationFailures:
    @pytest.mark.parametrize(
        "action,expected_label",
        [(NotificationAction.FIRE, "firing"), (NotificationAction.RESOLVE, "resolved")],
    )
    @patch("products.logs.backend.temporal.metrics.get_metric_meter")
    def test_increments_counter_with_event(self, mock_get_meter: MagicMock, action, expected_label):
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter
        mock_get_meter.return_value = mock_meter

        increment_notification_failures(action)

        mock_get_meter.assert_called_once_with({"event": expected_label})
        mock_meter.create_counter.assert_called_once()
        (name, _description), _ = mock_meter.create_counter.call_args
        assert name == "logs_alerting_notification_failures_total"
        mock_counter.add.assert_called_once_with(1)


class TestIncrementStateTransition:
    @patch("products.logs.backend.temporal.metrics.get_metric_meter")
    def test_increments_counter_with_from_and_to(self, mock_get_meter: MagicMock):
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter
        mock_get_meter.return_value = mock_meter

        increment_state_transition(AlertState.NOT_FIRING, AlertState.FIRING)

        mock_get_meter.assert_called_once_with({"from": "not_firing", "to": "firing"})
        (name, _description), _ = mock_meter.create_counter.call_args
        assert name == "logs_alerting_state_transitions_total"
        mock_counter.add.assert_called_once_with(1)


class TestRecordAlertsActive:
    @pytest.mark.parametrize("count", [17, 0])
    @patch("products.logs.backend.temporal.metrics.get_metric_meter")
    def test_sets_gauge_with_count(self, mock_get_meter: MagicMock, count: int):
        mock_meter = MagicMock()
        mock_gauge = MagicMock()
        mock_meter.create_gauge.return_value = mock_gauge
        mock_get_meter.return_value = mock_meter

        record_alerts_active(count)

        mock_get_meter.assert_called_once_with()
        (name, _description), _ = mock_meter.create_gauge.call_args
        assert name == "logs_alerting_alerts_active"
        mock_gauge.set.assert_called_once_with(count)


class TestRecordCheckDuration:
    @patch("products.logs.backend.temporal.metrics._record_histogram")
    def test_records_histogram_with_duration(self, mock_record: MagicMock):
        record_check_duration(150)
        mock_record.assert_called_once_with("logs_alerting_check_duration_ms", "Per-alert evaluation duration", 150)


class TestRecordScheduleToStartLatency:
    @patch("products.logs.backend.temporal.metrics._record_histogram")
    def test_records_latency_with_activity_type(self, mock_record: MagicMock):
        record_schedule_to_start_latency("check_alerts_activity", 250)
        mock_record.assert_called_once_with(
            "logs_alerting_schedule_to_start_ms",
            "Time between activity scheduling and start",
            250,
            {"activity_type": "check_alerts_activity"},
        )


class TestRecordSchedulerLag:
    @patch("products.logs.backend.temporal.metrics._record_histogram")
    def test_records_lag_as_histogram(self, mock_record: MagicMock):
        record_scheduler_lag(5000)
        mock_record.assert_called_once_with(
            "logs_alerting_scheduler_lag_ms", "Delay between alert due time and actual check time", 5000
        )


class TestRecordHistogram:
    @patch("products.logs.backend.temporal.metrics.get_metric_meter")
    def test_creates_histogram_and_records(self, mock_get_meter: MagicMock):
        from products.logs.backend.temporal.metrics import _record_histogram

        mock_meter = MagicMock()
        mock_hist = MagicMock()
        mock_meter.create_histogram_timedelta.return_value = mock_hist
        mock_get_meter.return_value = mock_meter

        _record_histogram("test_metric", "test description", 150, {"label": "value"})

        mock_get_meter.assert_called_once_with({"label": "value"})
        mock_meter.create_histogram_timedelta.assert_called_once_with(
            name="test_metric", description="test description", unit="ms"
        )
        mock_hist.record.assert_called_once_with(dt.timedelta(milliseconds=150))


class TestExecutionTimeRecorder:
    @patch("products.logs.backend.temporal.metrics.get_metric_meter")
    def test_records_completed_on_success(self, mock_get_meter: MagicMock):
        mock_meter = MagicMock()
        mock_hist = MagicMock()
        mock_meter.create_histogram_timedelta.return_value = mock_hist
        mock_get_meter.return_value = mock_meter

        with ExecutionTimeRecorder("test_histogram"):
            pass

        call_args = mock_get_meter.call_args[0][0]
        assert call_args["status"] == "COMPLETED"

    @patch("products.logs.backend.temporal.metrics.get_metric_meter")
    def test_records_failed_on_exception(self, mock_get_meter: MagicMock):
        mock_meter = MagicMock()
        mock_hist = MagicMock()
        mock_meter.create_histogram_timedelta.return_value = mock_hist
        mock_get_meter.return_value = mock_meter

        try:
            with ExecutionTimeRecorder("test_histogram"):
                raise ValueError("boom")
        except ValueError:
            pass

        call_args = mock_get_meter.call_args[0][0]
        assert call_args["status"] == "FAILED"
