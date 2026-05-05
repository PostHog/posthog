import datetime as dt
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

from parameterized import parameterized

from products.logs.backend.alert_state_machine import AlertState, NotificationAction
from products.logs.backend.temporal.metrics import (
    ALERTING_ACTIVITY_TYPES,
    AlertOutcome,
    ExecutionTimeRecorder,
    LogsAlertingMetricsInterceptor,
    increment_check_errors,
    increment_checkpoint_unavailable,
    increment_checks_total,
    increment_cohort_save_fallback,
    increment_notification_failures,
    increment_state_transition,
    record_alerts_active,
    record_check_duration,
    record_checkpoint_lag,
    record_clickhouse_duration,
    record_cohort_event_insert_duration,
    record_cohort_save_duration,
    record_cohort_size,
    record_cohort_update_duration,
    record_pending_alerts,
    record_schedule_to_start_latency,
    record_scheduler_lag,
    record_semaphore_wait,
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


class TestRecordCheckpointLag:
    @pytest.mark.parametrize(
        "lag_seconds,expected",
        [
            (0, 0),  # checkpoint == now
            (15, 15),  # typical healthy lag
            (300, 300),  # backlog starting
            (-60, 0),  # checkpoint somehow ahead of now — clamped to 0
        ],
    )
    @patch("products.logs.backend.temporal.metrics.get_metric_meter")
    def test_records_positive_lag(self, mock_get_meter: MagicMock, lag_seconds: int, expected: int):
        mock_meter = MagicMock()
        mock_gauge = MagicMock()
        mock_meter.create_gauge.return_value = mock_gauge
        mock_get_meter.return_value = mock_meter

        now = dt.datetime(2025, 1, 1, 0, 0, 0)
        checkpoint = now - dt.timedelta(seconds=lag_seconds)
        record_checkpoint_lag(now, checkpoint)

        (name, _description), _ = mock_meter.create_gauge.call_args
        assert name == "logs_alerting_ingestion_checkpoint_lag_seconds"
        mock_gauge.set.assert_called_once_with(expected)


class TestIncrementCheckpointUnavailable:
    @patch("products.logs.backend.temporal.metrics.get_metric_meter")
    def test_increments_counter(self, mock_get_meter: MagicMock):
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter
        mock_get_meter.return_value = mock_meter

        increment_checkpoint_unavailable()

        (name, _description), _ = mock_meter.create_counter.call_args
        assert name == "logs_alerting_checkpoint_unavailable_total"
        mock_counter.add.assert_called_once_with(1)


class TestRecordCheckDuration:
    @patch("products.logs.backend.temporal.metrics._record_histogram")
    def test_records_histogram_with_duration(self, mock_record: MagicMock):
        record_check_duration(150)
        mock_record.assert_called_once_with(
            "logs_alerting_check_duration_ms",
            "Per-alert end-to-end duration (eval + dispatch); cohort bulk save excluded — see logs_alerting_cohort_save_ms",
            150,
        )


class TestRecordClickhouseDuration:
    @patch("products.logs.backend.temporal.metrics._record_histogram")
    def test_records_histogram_with_duration(self, mock_record: MagicMock):
        record_clickhouse_duration(2_500)
        mock_record.assert_called_once_with(
            "logs_alerting_clickhouse_duration_ms",
            "ClickHouse query wall time for a single alert evaluation",
            2_500,
        )


class TestRecordSemaphoreWait:
    @patch("products.logs.backend.temporal.metrics._record_histogram")
    def test_records_histogram_with_wait(self, mock_record: MagicMock):
        record_semaphore_wait(800)
        mock_record.assert_called_once_with(
            "logs_alerting_semaphore_wait_ms",
            "Time an alert spent waiting on the per-cycle concurrency semaphore",
            800,
        )


class TestRecordCohortSaveSubstageDurations:
    @parameterized.expand(
        [
            (
                "save_total",
                record_cohort_save_duration,
                "logs_alerting_cohort_save_ms",
                "Postgres write time for the per-cohort bulk save (full transaction: bulk_create + bulk_update)",
                45,
            ),
            (
                "event_insert",
                record_cohort_event_insert_duration,
                "logs_alerting_cohort_event_insert_ms",
                "Postgres bulk_create time for LogsAlertEvent rows in a cohort (only on state changes or errors)",
                12,
            ),
            (
                "cohort_update",
                record_cohort_update_duration,
                "logs_alerting_cohort_update_ms",
                "Postgres bulk_update time for LogsAlertConfiguration rows in a cohort",
                28,
            ),
            (
                "cohort_size",
                record_cohort_size,
                "logs_alerting_cohort_size",
                "Number of alerts in a cohort sharing one batched ClickHouse query and one bulk Postgres save",
                17,
            ),
        ]
    )
    @patch("products.logs.backend.temporal.metrics._record_histogram")
    def test_records_histogram_with_duration(
        self, _name: str, fn: Any, metric_name: str, description: str, sample_value: int, mock_record: MagicMock
    ):
        fn(sample_value)
        mock_record.assert_called_once_with(metric_name, description, sample_value)


class TestIncrementCohortSaveFallback:
    @patch("products.logs.backend.temporal.metrics.get_metric_meter")
    def test_increments_counter_with_reason(self, mock_get_meter: MagicMock):
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter
        mock_get_meter.return_value = mock_meter

        increment_cohort_save_fallback("integrity_error")

        mock_get_meter.assert_called_once_with({"reason": "integrity_error"})
        (name, _description), _ = mock_meter.create_counter.call_args
        assert name == "logs_alerting_cohort_save_fallback_total"
        mock_counter.add.assert_called_once_with(1)


class TestRecordPendingAlerts:
    @pytest.mark.parametrize("count", [42, 0])
    @patch("products.logs.backend.temporal.metrics.get_metric_meter")
    def test_sets_gauge_value(self, mock_get_meter: MagicMock, count: int):
        mock_meter = MagicMock()
        mock_gauge = MagicMock()
        mock_meter.create_gauge.return_value = mock_gauge
        mock_get_meter.return_value = mock_meter

        record_pending_alerts(count)

        (name, _description), _ = mock_meter.create_gauge.call_args
        assert name == "logs_alerting_pending_alerts"
        mock_gauge.set.assert_called_once_with(count)


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
