import datetime as dt

import pytest
from unittest.mock import MagicMock, patch

from products.logs.backend.temporal.metrics import ExecutionTimeRecorder, record_checkpoint_lag, record_coordinator_poll


def test_record_coordinator_poll_exposes_saturation_and_freshness() -> None:
    meter = MagicMock()
    counters: dict[str, MagicMock] = {}
    gauges: dict[str, MagicMock] = {}
    meter.create_counter.side_effect = lambda name, _description: counters.setdefault(name, MagicMock())
    meter.create_gauge.side_effect = lambda name, _description: gauges.setdefault(name, MagicMock())
    oldest_due_at = dt.datetime(2026, 9, 11, 10, 0, tzinfo=dt.UTC)

    with (
        patch("products.logs.backend.temporal.metrics.get_metric_meter", return_value=meter) as get_meter,
        patch("products.logs.backend.temporal.metrics.time.time", return_value=1_789_128_000.0),
        patch("products.logs.backend.temporal.metrics.dt.datetime", wraps=dt.datetime) as datetime_mock,
    ):
        datetime_mock.now.return_value = oldest_due_at + dt.timedelta(hours=1)
        record_coordinator_poll(
            selected_count=300,
            max_alerts_per_run=300,
            has_more=True,
            oldest_due_at=oldest_due_at,
        )

    assert get_meter.call_args_list[0].args[0] == {"outcome": "saturated"}
    counters["logs_alerting_coordinator_polls_total"].add.assert_called_once_with(1)
    counters["logs_alerting_coordinator_selected_total"].add.assert_called_once_with(300)
    gauges["logs_alerting_coordinator_max_alerts_per_run"].set.assert_called_once_with(300)
    gauges["logs_alerting_coordinator_oldest_due_age_seconds"].set.assert_called_once_with(3600)
    gauges["logs_alerting_coordinator_last_successful_poll_timestamp_seconds"].set.assert_called_once_with(
        1_789_128_000.0
    )


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

        mock_gauge.set.assert_called_once_with(expected)


class TestRecordHistogram:
    @patch("products.logs.backend.temporal.metrics.get_metric_meter")
    def test_creates_histogram_and_records(self, mock_get_meter: MagicMock):
        from products.logs.backend.temporal.metrics import _record_histogram

        mock_meter = MagicMock()
        mock_hist = MagicMock()
        mock_meter.create_histogram_timedelta.return_value = mock_hist
        mock_get_meter.return_value = mock_meter

        _record_histogram("test_metric", "test description", 150, {"label": "value"})

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
