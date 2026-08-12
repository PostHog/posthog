from products.experiments.backend.temporal.canary_activities import (
    report_experiment_canary_results,
    run_experiment_metric_canary,
    sample_experiment_canary_targets,
)
from products.experiments.backend.temporal.canary_workflow import ExperimentPrecomputeCanaryWorkflow
from products.experiments.backend.temporal.recalculation_activities import (
    calculate_experiment_metric_for_recalculation,
    discover_experiment_metrics,
    update_recalculation_progress,
)
from products.experiments.backend.temporal.recalculation_workflow import ExperimentMetricsRecalculationWorkflow

EXPERIMENT_CANARY_WORKFLOWS = [
    ExperimentPrecomputeCanaryWorkflow,
]
EXPERIMENT_CANARY_ACTIVITIES = [
    sample_experiment_canary_targets,
    run_experiment_metric_canary,
    report_experiment_canary_results,
]

WORKFLOWS = [
    ExperimentMetricsRecalculationWorkflow,
    *EXPERIMENT_CANARY_WORKFLOWS,
]
ACTIVITIES = [
    discover_experiment_metrics,
    calculate_experiment_metric_for_recalculation,
    update_recalculation_progress,
    *EXPERIMENT_CANARY_ACTIVITIES,
]

__all__ = [
    "ACTIVITIES",
    "EXPERIMENT_CANARY_ACTIVITIES",
    "EXPERIMENT_CANARY_WORKFLOWS",
    "WORKFLOWS",
    "ExperimentMetricsRecalculationWorkflow",
    "ExperimentPrecomputeCanaryWorkflow",
    "calculate_experiment_metric_for_recalculation",
    "discover_experiment_metrics",
    "report_experiment_canary_results",
    "run_experiment_metric_canary",
    "sample_experiment_canary_targets",
    "update_recalculation_progress",
]
