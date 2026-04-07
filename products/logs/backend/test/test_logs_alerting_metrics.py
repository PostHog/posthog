import datetime as dt

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

from products.logs.backend.temporal.metrics import (
    ALERTING_ACTIVITY_TYPES,
    AlertOutcome,
    ExecutionTimeRecorder,
    LogsAlertingMetricsInterceptor,
    increment_checks_total,
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
