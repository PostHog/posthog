from datetime import UTC, datetime, timedelta

from unittest.mock import MagicMock, patch

from products.exports.backend.temporal.subscriptions.metrics import record_scheduler_fetch


def test_record_scheduler_fetch_emits_progress_and_saturation_signals() -> None:
    meter = MagicMock()
    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.metrics.get_metric_meter",
            return_value=meter,
        ),
        patch("products.exports.backend.temporal.subscriptions.metrics.time.time", return_value=1_789_128_000.0),
    ):
        record_scheduler_fetch(
            selected_count=500,
            oldest_due_at=now - timedelta(minutes=45),
            now=now,
            has_more=True,
        )

    meter.with_additional_attributes.assert_called_once_with({"outcome": "saturated"})
    run_meter = meter.with_additional_attributes.return_value
    run_meter.create_counter.return_value.add.assert_called_once_with(1)
    meter.create_counter.return_value.add.assert_called_once_with(500)
    meter.create_gauge_float.return_value.set.assert_any_call(2_700.0)
    meter.create_gauge_float.return_value.set.assert_any_call(1_789_128_000.0)
