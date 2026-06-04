from unittest.mock import MagicMock, patch

from django.conf import settings

from parameterized import parameterized
from temporalio.worker import ActivityInboundInterceptor

from posthog.temporal.ai_observability.metrics import ExecutionTimeRecorder
from posthog.temporal.common.interceptor import is_task_queue_supported

from products.experiments.backend.temporal.recalculation_metrics import (
    EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_BUCKETS,
    EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_METRICS,
    ExperimentsRecalculationMetricsInterceptor,
    increment_workflow_finished,
)


def test_registered_on_general_purpose_queue():
    # Pins the interceptor's `task_queue` ClassVar — without it, `is_task_queue_supported` filters the
    # interceptor out of every worker and the metrics emit nothing.
    assert is_task_queue_supported(settings.GENERAL_PURPOSE_TASK_QUEUE, ExperimentsRecalculationMetricsInterceptor)


def test_metric_names_defined():
    assert (
        "experiment_metrics_recalculation_activity_execution_latency"
        in EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_METRICS
    )
    assert (
        "experiment_metrics_recalculation_workflow_execution_latency"
        in EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_METRICS
    )


def test_buckets_sorted_ascending_and_floats():
    buckets = EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_BUCKETS
    assert buckets == sorted(buckets)
    assert all(isinstance(b, float) for b in buckets)


def test_interceptor_wraps_activity():
    class _Sentinel(ActivityInboundInterceptor):
        pass

    interceptor = ExperimentsRecalculationMetricsInterceptor()
    wrapped = interceptor.intercept_activity(_Sentinel(None))  # type: ignore[arg-type]
    assert isinstance(wrapped, ActivityInboundInterceptor)


@parameterized.expand(
    [
        # Pins the contract that the histogram name passed to ExecutionTimeRecorder matches the constant we
        # registered for bucket overrides in posthog/temporal/common/worker.py. If a future refactor renames
        # either side without renaming the other, the worker's bucket override silently becomes dead config
        # (no histogram with that name ever fires, so the override key never resolves).
        ("activity_histogram", "experiment_metrics_recalculation_activity_execution_latency"),
        ("workflow_histogram", "experiment_metrics_recalculation_workflow_execution_latency"),
    ]
)
def test_registered_histogram_names_are_emitted(name: str, histogram_name: str):
    assert histogram_name in EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_METRICS

    mock_meter = MagicMock()
    mock_hist = MagicMock()
    mock_meter.create_histogram_timedelta.return_value = mock_hist

    with patch("posthog.temporal.ai_observability.metrics.get_metric_meter", return_value=mock_meter):
        with ExecutionTimeRecorder(histogram_name):
            pass

    mock_meter.create_histogram_timedelta.assert_called_once()
    assert mock_meter.create_histogram_timedelta.call_args.kwargs["name"] == histogram_name
    mock_hist.record.assert_called_once()


@parameterized.expand(
    [
        ("completed_status", "completed"),
        ("failed_status", "failed"),
    ]
)
def test_increment_workflow_finished_emits_status_attribute(name: str, status: str):
    # Counter is the only workflow-level lifecycle signal that distinguishes business outcomes (all-succeeded
    # vs at-least-one-failed). The status attribute is what `recalc-success-rate` dashboards key off.
    mock_meter = MagicMock()
    mock_meter_with_attrs = MagicMock()
    mock_counter = MagicMock()
    mock_meter.with_additional_attributes.return_value = mock_meter_with_attrs
    mock_meter_with_attrs.create_counter.return_value = mock_counter

    with patch(
        "products.experiments.backend.temporal.recalculation_metrics.workflow.metric_meter",
        return_value=mock_meter,
    ):
        increment_workflow_finished(status)

    mock_meter.with_additional_attributes.assert_called_once_with({"status": status})
    mock_meter_with_attrs.create_counter.assert_called_once()
    assert (
        mock_meter_with_attrs.create_counter.call_args.args[0] == "experiment_metrics_recalculation_workflow_finished"
    )
    mock_counter.add.assert_called_once_with(1)
