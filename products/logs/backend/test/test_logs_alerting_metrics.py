import datetime as dt

import pytest
from unittest.mock import MagicMock, patch

from products.logs.backend.temporal.metrics import ExecutionTimeRecorder, record_checkpoint_lag


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
