from products.experiments.backend.facade.temporal import TEMPORAL
from products.experiments.backend.temporal.canary_workflow import ExperimentPrecomputeCanaryWorkflow
from products.experiments.backend.temporal.enrollment_census_activities import run_experiment_enrollment_census
from products.experiments.backend.temporal.enrollment_census_workflow import (
    ExperimentPrecomputeEnrollmentCensusWorkflow,
)
from products.experiments.backend.temporal.recalculation.activities import calculate_experiment_metric_for_recalculation
from products.experiments.backend.temporal.recalculation.workflow import ExperimentMetricsRecalculationWorkflow
from products.experiments.backend.temporal.registry import (
    ACTIVITIES,
    EXPERIMENT_RECALCULATION_ACTIVITY_QUEUE_ACTIVITIES,
    WORKFLOWS,
)
from products.experiments.backend.temporal.scheduled_recalculation_activities import (
    check_experiment_exposures,
    discover_scheduled_recalculation_candidates,
    start_scheduled_recalculation,
    wait_for_scheduled_recalculation,
)
from products.experiments.backend.temporal.scheduled_recalculation_workflow import (
    ScheduledExperimentRecalculationWorkflow,
)


def test_activities_registered():
    names = {activity.__name__ for activity in ACTIVITIES}
    assert names == {
        "discover_experiment_metrics",
        "calculate_experiment_metric_for_recalculation",
        "update_recalculation_progress",
        "record_metric_out_of_time_failure",
        "sample_experiment_canary_targets",
        "run_experiment_metric_canary",
        "report_experiment_canary_results",
        "run_experiment_enrollment_census",
        "discover_scheduled_recalculation_candidates",
        "check_experiment_exposures",
        "start_scheduled_recalculation",
        "wait_for_scheduled_recalculation",
    }


def test_workflow_registered():
    assert WORKFLOWS == [
        ExperimentMetricsRecalculationWorkflow,
        ExperimentPrecomputeCanaryWorkflow,
        ExperimentPrecomputeEnrollmentCensusWorkflow,
        ScheduledExperimentRecalculationWorkflow,
    ]


def test_scheduled_workflows_registered_on_general_purpose_queue():
    # The canary and census schedules dispatch to the general-purpose queue; membership in
    # the product WORKFLOWS list alone registers on the recalculation queue only. A workflow
    # missing here leaves its scheduled runs retrying "not registered on this worker" forever.
    (general_purpose,) = [
        binding for binding in TEMPORAL.queues if binding.queue_setting == "GENERAL_PURPOSE_TASK_QUEUE"
    ]
    assert {
        ExperimentPrecomputeCanaryWorkflow,
        ExperimentPrecomputeEnrollmentCensusWorkflow,
        ScheduledExperimentRecalculationWorkflow,
    } <= set(general_purpose.workflows)
    assert {
        run_experiment_enrollment_census,
        discover_scheduled_recalculation_candidates,
        check_experiment_exposures,
        start_scheduled_recalculation,
        wait_for_scheduled_recalculation,
    } <= set(general_purpose.activities)


def test_calc_activity_registered_on_recalculation_and_activity_queues():
    (recalculation,) = [
        binding for binding in TEMPORAL.queues if ExperimentMetricsRecalculationWorkflow in binding.workflows
    ]
    assert recalculation.queue_setting == "EXPERIMENTS_RECALCULATION_TASK_QUEUE"
    assert calculate_experiment_metric_for_recalculation in recalculation.activities
    activity_queues = {
        binding.queue_setting: binding.activities
        for binding in TEMPORAL.queues
        if not binding.workflows and calculate_experiment_metric_for_recalculation in binding.activities
    }
    assert activity_queues == dict.fromkeys(
        (
            "EXPERIMENTS_RECALCULATION_ACTIVITY_TASK_QUEUE",
            "EXPERIMENTS_RECALCULATION_PRECOMPUTE_TASK_QUEUE",
            "EXPERIMENTS_RECALCULATION_BUILD_TASK_QUEUE",
            "EXPERIMENTS_RECALCULATION_DIRECT_HEAVY_TASK_QUEUE",
        ),
        tuple(EXPERIMENT_RECALCULATION_ACTIVITY_QUEUE_ACTIVITIES),
    )
    assert EXPERIMENT_RECALCULATION_ACTIVITY_QUEUE_ACTIVITIES == [calculate_experiment_metric_for_recalculation]
