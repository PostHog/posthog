from temporalio.worker import ActivityInboundInterceptor

from products.experiments.backend.temporal.recalculation_metrics import (
    EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_BUCKETS,
    EXPERIMENT_METRICS_RECALCULATION_LATENCY_HISTOGRAM_METRICS,
    ExperimentsRecalculationMetricsInterceptor,
)


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
