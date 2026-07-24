import datetime as dt
from contextlib import nullcontext

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


@pytest.mark.parametrize(
    "execution_error,expected_status,expected_exception",
    [
        pytest.param(None, "COMPLETED", "", id="completed"),
        pytest.param(ValueError("boom"), "FAILED", "ValueError", id="failed"),
    ],
)
def test_execution_time_recorder_attributes(
    execution_error: Exception | None, expected_status: str, expected_exception: str
) -> None:
    mock_meter = MagicMock()
    mock_histogram = MagicMock()
    mock_meter.create_histogram_timedelta.return_value = mock_histogram
    mock_get_meter = MagicMock(return_value=mock_meter)

    with (
        patch("products.logs.backend.temporal.metrics.get_metric_meter", new=mock_get_meter),
        patch("posthog.temporal.common.metrics.get_metric_meter", new=mock_get_meter),
        pytest.raises(ValueError, match="boom") if execution_error else nullcontext(),
    ):
        with ExecutionTimeRecorder(
            "logs_alerting_cycle_duration_ms",
            description="Full alert check cycle duration",
            histogram_attributes={"activity_type": "discover_cohorts_activity"},
        ):
            if execution_error:
                raise execution_error

    mock_get_meter.assert_called_once_with(
        {
            "activity_type": "discover_cohorts_activity",
            "status": expected_status,
            "exception": expected_exception,
        }
    )
    mock_meter.create_histogram_timedelta.assert_called_once_with(
        name="logs_alerting_cycle_duration_ms",
        description="Full alert check cycle duration",
        unit="ms",
    )
    mock_histogram.record.assert_called_once()
