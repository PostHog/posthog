from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

from unittest.mock import MagicMock, patch

from prometheus_client import CollectorRegistry

from products.exports.backend.temporal.subscriptions.metrics import record_scheduler_fetch, record_scheduler_progress


def _capture_instruments(meter: MagicMock, *, counters: dict[str, MagicMock], gauges: dict[str, MagicMock]) -> None:
    meter.create_counter.side_effect = lambda name, *_args: counters.setdefault(name, MagicMock())
    meter.create_gauge_float.side_effect = lambda name, *_args: gauges.setdefault(name, MagicMock())


def test_record_scheduler_fetch_emits_progress_and_saturation_signals() -> None:
    meter = MagicMock()
    counters: dict[str, MagicMock] = {}
    gauges: dict[str, MagicMock] = {}
    _capture_instruments(meter, counters=counters, gauges=gauges)
    registry = CollectorRegistry()
    now = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.metrics.get_metric_meter",
            return_value=meter,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.metrics.pushed_metrics_registry",
            return_value=nullcontext(registry),
        ),
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
    counters["subscriptions_scheduler_selected"].add.assert_called_once_with(500)
    assert registry.get_sample_value("posthog_subscriptions_scheduler_oldest_due_age_seconds") == 2_700.0
    assert registry.get_sample_value("posthog_subscriptions_scheduler_last_successful_fetch_timestamp_seconds") == (
        now.timestamp()
    )


def test_record_scheduler_fetch_does_not_replace_oldest_due_age_for_later_pages() -> None:
    meter = MagicMock()
    counters: dict[str, MagicMock] = {}
    gauges: dict[str, MagicMock] = {}
    _capture_instruments(meter, counters=counters, gauges=gauges)
    pushed_registry = MagicMock()

    with (
        patch(
            "products.exports.backend.temporal.subscriptions.metrics.get_metric_meter",
            return_value=meter,
        ),
        patch(
            "products.exports.backend.temporal.subscriptions.metrics.pushed_metrics_registry",
            new=pushed_registry,
        ),
    ):
        record_scheduler_fetch(
            selected_count=100,
            oldest_due_at=datetime(2026, 9, 11, 12, 0, tzinfo=UTC),
            now=datetime(2026, 9, 11, 12, 5, tzinfo=UTC),
            has_more=True,
            record_oldest_due_age=False,
        )

    pushed_registry.assert_not_called()


def test_record_scheduler_progress_emits_backlog_and_dispatch_signals() -> None:
    meter = MagicMock()
    counters: dict[str, MagicMock] = {}
    gauges: dict[str, MagicMock] = {}
    _capture_instruments(meter, counters=counters, gauges=gauges)

    with patch(
        "products.exports.backend.temporal.subscriptions.metrics.get_metric_meter",
        return_value=meter,
    ):
        record_scheduler_progress(
            total_count=250,
            processed_count=100,
            remaining_count=150,
            page_number=1,
            completed_count=98,
            already_running_count=2,
            failed_count=1,
            completed=False,
        )

    gauges["subscriptions_scheduler_cohort_total"].set.assert_called_once_with(250.0)
    gauges["subscriptions_scheduler_cohort_processed"].set.assert_called_once_with(100.0)
    gauges["subscriptions_scheduler_cohort_remaining"].set.assert_called_once_with(150.0)
    counters["subscriptions_scheduler_pages"].add.assert_called_once_with(1)
    counters["subscriptions_scheduler_children_completed"].add.assert_called_once_with(98)
    counters["subscriptions_scheduler_children_already_running"].add.assert_called_once_with(2)
    counters["subscriptions_scheduler_children_failed"].add.assert_called_once_with(1)
    counters["subscriptions_scheduler_cohorts_started"].add.assert_called_once_with(1)
    assert "subscriptions_scheduler_cohorts_completed" not in counters


def test_record_scheduler_progress_emits_completion_timestamp() -> None:
    meter = MagicMock()
    counters: dict[str, MagicMock] = {}
    gauges: dict[str, MagicMock] = {}
    _capture_instruments(meter, counters=counters, gauges=gauges)

    with patch(
        "products.exports.backend.temporal.subscriptions.metrics.get_metric_meter",
        return_value=meter,
    ):
        record_scheduler_progress(
            total_count=250,
            processed_count=250,
            remaining_count=0,
            page_number=3,
            completed_count=50,
            already_running_count=0,
            failed_count=0,
            completed=True,
            completed_at=datetime.fromtimestamp(1_789_128_000.0, tz=UTC),
        )

    gauges["subscriptions_scheduler_last_completed_timestamp_seconds"].set.assert_called_once_with(1_789_128_000.0)
    counters["subscriptions_scheduler_cohorts_completed"].add.assert_called_once_with(1)
    counters["subscriptions_scheduler_children_completed"].add.assert_called_once_with(50)
    counters["subscriptions_scheduler_children_failed"].add.assert_called_once_with(0)
