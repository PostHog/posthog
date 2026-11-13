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
from products.experiments.backend.temporal.recalculation.activities import (
    calculate_experiment_metric_for_recalculation,
    discover_experiment_metrics,
    record_metric_out_of_time_failure,
    update_recalculation_progress,
)
from products.experiments.backend.temporal.recalculation.workflow import ExperimentMetricsRecalculationWorkflow
from products.experiments.backend.temporal.scheduled_recalculation_activities import (
    check_experiment_exposures,
    discover_scheduled_recalculation_candidates,
    start_scheduled_recalculation,
    wait_for_scheduled_recalculation,
)
from products.experiments.backend.temporal.scheduled_recalculation_workflow import (
    ScheduledExperimentRecalculationWorkflow,
)
from products.experiments.backend.temporal.timeseries.activities import (
    backfill_experiment_metric,
    calculate_experiment_regular_metric,
    calculate_experiment_saved_metric,
    create_recalculation_from_timeseries,
    get_experiment_regular_metrics_for_hour,
    get_experiment_saved_metrics_for_hour,
)
from products.experiments.backend.temporal.timeseries.workflows import (
    ExperimentRegularMetricsWorkflow,
    ExperimentSavedMetricsWorkflow,
    ExperimentTimeseriesRecalculationWorkflow,
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
EXPERIMENT_SCHEDULED_RECALCULATION_WORKFLOWS = [
    ScheduledExperimentRecalculationWorkflow,
]
EXPERIMENT_SCHEDULED_RECALCULATION_ACTIVITIES = [
    discover_scheduled_recalculation_candidates,
    check_experiment_exposures,
    start_scheduled_recalculation,
    wait_for_scheduled_recalculation,
]
EXPERIMENT_RECALCULATION_ACTIVITY_QUEUE_ACTIVITIES = [
    calculate_experiment_metric_for_recalculation,
]

WORKFLOWS = [
    ExperimentMetricsRecalculationWorkflow,
    *EXPERIMENT_CANARY_WORKFLOWS,
    *EXPERIMENT_ENROLLMENT_CENSUS_WORKFLOWS,
    *EXPERIMENT_SCHEDULED_RECALCULATION_WORKFLOWS,
]
ACTIVITIES = [
    discover_experiment_metrics,
    calculate_experiment_metric_for_recalculation,
    update_recalculation_progress,
    record_metric_out_of_time_failure,
    *EXPERIMENT_CANARY_ACTIVITIES,
    *EXPERIMENT_ENROLLMENT_CENSUS_ACTIVITIES,
    *EXPERIMENT_SCHEDULED_RECALCULATION_ACTIVITIES,
]

TIMESERIES_WORKFLOWS = [
    ExperimentRegularMetricsWorkflow,
    ExperimentSavedMetricsWorkflow,
    ExperimentTimeseriesRecalculationWorkflow,
]
TIMESERIES_ACTIVITIES = [
    get_experiment_regular_metrics_for_hour,
    calculate_experiment_regular_metric,
    get_experiment_saved_metrics_for_hour,
    calculate_experiment_saved_metric,
    create_recalculation_from_timeseries,
    backfill_experiment_metric,
]
