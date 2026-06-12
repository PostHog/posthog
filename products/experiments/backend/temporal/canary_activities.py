"""Temporal activity entrypoints for the experiment precompute canary.

Thin ``@temporalio.activity.defn`` wrappers; the implementations live in ``canary_logic``.
"""

import temporalio.activity

from posthog.sync import database_sync_to_async

from products.experiments.backend.temporal.canary_logic import (
    report_canary_results_sync,
    run_metric_canary_sync,
    sample_canary_targets_sync,
)
from products.experiments.backend.temporal.models import (
    CanaryMetricResult,
    CanaryMetricTarget,
    CanaryReportInputs,
    ExperimentPrecomputeCanaryInputs,
)


@temporalio.activity.defn
async def sample_experiment_canary_targets(inputs: ExperimentPrecomputeCanaryInputs) -> list[CanaryMetricTarget]:
    """Pick the (experiment, metric) pairs for this canary run; uuids only, definitions resolve later."""
    return await database_sync_to_async(sample_canary_targets_sync)(inputs)


@temporalio.activity.defn
async def run_experiment_metric_canary(target: CanaryMetricTarget) -> CanaryMetricResult:
    """Run one metric through both execution paths (precomputed twice, direct once) and compare."""
    return await database_sync_to_async(run_metric_canary_sync)(target)


@temporalio.activity.defn
async def report_experiment_canary_results(report: CanaryReportInputs) -> None:
    """Push Prometheus gauges and post the Slack alert when any metric diverged."""
    return await database_sync_to_async(report_canary_results_sync)(report)
