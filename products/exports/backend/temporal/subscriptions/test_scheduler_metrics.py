from datetime import UTC, datetime, timedelta

from unittest.mock import MagicMock, patch

from products.exports.backend.temporal.subscriptions.metrics import record_scheduler_fetch, record_scheduler_progress


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


def test_record_scheduler_progress_emits_backlog_and_dispatch_signals() -> None:
    meter = MagicMock()

    with patch(
        "products.exports.backend.temporal.subscriptions.metrics.get_metric_meter",
        return_value=meter,
    ):
        record_scheduler_progress(
            total_count=250,
            processed_count=100,
            remaining_count=150,
            page_number=1,
            started_count=98,
            already_running_count=2,
            completed=False,
        )

    gauge = meter.create_gauge_float.return_value
    gauge.set.assert_any_call(250.0)
    gauge.set.assert_any_call(100.0)
    gauge.set.assert_any_call(150.0)
    meter.create_counter.return_value.add.assert_any_call(1)
    meter.create_counter.return_value.add.assert_any_call(98)
    meter.create_counter.return_value.add.assert_any_call(2)
    counter_names = [call.args[0] for call in meter.create_counter.call_args_list]
    assert "subscriptions_scheduler_cohorts_started" in counter_names
    assert "subscriptions_scheduler_cohorts_completed" not in counter_names


def test_record_scheduler_progress_emits_completion_timestamp() -> None:
    meter = MagicMock()

    with patch(
        "products.exports.backend.temporal.subscriptions.metrics.get_metric_meter",
        return_value=meter,
    ):
        record_scheduler_progress(
            total_count=250,
            processed_count=250,
            remaining_count=0,
            page_number=3,
            started_count=50,
            already_running_count=0,
            completed=True,
            completed_at=datetime.fromtimestamp(1_789_128_000.0, tz=UTC),
        )

    meter.create_gauge_float.return_value.set.assert_any_call(1_789_128_000.0)
    counter_names = [call.args[0] for call in meter.create_counter.call_args_list]
    assert "subscriptions_scheduler_cohorts_completed" in counter_names
