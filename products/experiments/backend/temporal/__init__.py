from products.experiments.backend.temporal.canary_activities import (
    report_experiment_canary_results,
    run_experiment_metric_canary,
    sample_experiment_canary_targets,
)
from products.experiments.backend.temporal.canary_workflow import ExperimentPrecomputeCanaryWorkflow
from products.experiments.backend.temporal.enrollment_census_activities import run_experiment_enrollment_census
from products.experiments.backend.temporal.enrollment_census_workflow import (
    ExperimentPrecomputeEnrollmentCensusWorkflow,
)
from products.experiments.backend.temporal.recalculation_activities import (
    calculate_experiment_metric_for_recalculation,
    discover_experiment_metrics,
    update_recalculation_progress,
)
from products.experiments.backend.temporal.recalculation_workflow import ExperimentMetricsRecalculationWorkflow
from products.experiments.backend.temporal.scheduled_recalculation_activities import (
    check_experiment_exposures,
    discover_scheduled_recalculation_candidates,
    start_scheduled_recalculation,
)
from products.experiments.backend.temporal.scheduled_recalculation_workflow import (
    ScheduledExperimentRecalculationWorkflow,
)

EXPERIMENT_CANARY_WORKFLOWS = [
    ExperimentPrecomputeCanaryWorkflow,
]
EXPERIMENT_CANARY_ACTIVITIES = [
    sample_experiment_canary_targets,
    run_experiment_metric_canary,
    report_experiment_canary_results,
]
EXPERIMENT_ENROLLMENT_CENSUS_WORKFLOWS = [
    ExperimentPrecomputeEnrollmentCensusWorkflow,
]
EXPERIMENT_ENROLLMENT_CENSUS_ACTIVITIES = [
    run_experiment_enrollment_census,
]
SCHEDULED_RECALCULATION_WORKFLOWS = [
    ScheduledExperimentRecalculationWorkflow,
]
SCHEDULED_RECALCULATION_ACTIVITIES = [
    discover_scheduled_recalculation_candidates,
    check_experiment_exposures,
    start_scheduled_recalculation,
]

WORKFLOWS = [
    ExperimentMetricsRecalculationWorkflow,
    *EXPERIMENT_CANARY_WORKFLOWS,
    *EXPERIMENT_ENROLLMENT_CENSUS_WORKFLOWS,
    *SCHEDULED_RECALCULATION_WORKFLOWS,
]
ACTIVITIES = [
    discover_experiment_metrics,
    calculate_experiment_metric_for_recalculation,
    update_recalculation_progress,
    *EXPERIMENT_CANARY_ACTIVITIES,
    *EXPERIMENT_ENROLLMENT_CENSUS_ACTIVITIES,
    *SCHEDULED_RECALCULATION_ACTIVITIES,
]

__all__ = [
    "ACTIVITIES",
    "EXPERIMENT_CANARY_ACTIVITIES",
    "EXPERIMENT_CANARY_WORKFLOWS",
    "EXPERIMENT_ENROLLMENT_CENSUS_ACTIVITIES",
    "EXPERIMENT_ENROLLMENT_CENSUS_WORKFLOWS",
    "SCHEDULED_RECALCULATION_ACTIVITIES",
    "SCHEDULED_RECALCULATION_WORKFLOWS",
    "WORKFLOWS",
    "ExperimentMetricsRecalculationWorkflow",
    "ExperimentPrecomputeCanaryWorkflow",
    "ExperimentPrecomputeEnrollmentCensusWorkflow",
    "ScheduledExperimentRecalculationWorkflow",
    "calculate_experiment_metric_for_recalculation",
    "check_experiment_exposures",
    "discover_experiment_metrics",
    "discover_scheduled_recalculation_candidates",
    "report_experiment_canary_results",
    "run_experiment_enrollment_census",
    "run_experiment_metric_canary",
    "sample_experiment_canary_targets",
    "start_scheduled_recalculation",
    "update_recalculation_progress",
]
