from django.test import override_settings

from posthog.temporal.registry import create_worker_bag_collector

from products.experiments.backend.temporal import ACTIVITIES, WORKFLOWS
from products.experiments.backend.temporal.canary_workflow import ExperimentPrecomputeCanaryWorkflow
from products.experiments.backend.temporal.enrollment_census_activities import run_experiment_enrollment_census
from products.experiments.backend.temporal.enrollment_census_workflow import (
    ExperimentPrecomputeEnrollmentCensusWorkflow,
)
from products.experiments.backend.temporal.recalculation_workflow import ExperimentMetricsRecalculationWorkflow


def test_activities_registered():
    names = {activity.__name__ for activity in ACTIVITIES}
    assert names == {
        "discover_experiment_metrics",
        "calculate_experiment_metric_for_recalculation",
        "update_recalculation_progress",
        "sample_experiment_canary_targets",
        "run_experiment_metric_canary",
        "report_experiment_canary_results",
        "run_experiment_enrollment_census",
    }


def test_workflow_registered():
    assert WORKFLOWS == [
        ExperimentMetricsRecalculationWorkflow,
        ExperimentPrecomputeCanaryWorkflow,
        ExperimentPrecomputeEnrollmentCensusWorkflow,
    ]


def test_scheduled_workflows_registered_on_general_purpose_queue() -> None:
    # The canary and census schedules dispatch to the general-purpose queue; membership in
    # the product WORKFLOWS list alone registers on the recalculation queue only. A workflow
    # missing here leaves its scheduled runs retrying "not registered on this worker" forever.
    # Give the general-purpose queue a separate name because test settings merge queues,
    # which would hide a missing registration behind the recalculation queue's definitions.
    with override_settings(GENERAL_PURPOSE_TASK_QUEUE="general-purpose-registration-test"):
        bag = create_worker_bag_collector().collect("general-purpose-registration-test")

    assert ExperimentPrecomputeCanaryWorkflow in bag.workflows
    assert ExperimentPrecomputeEnrollmentCensusWorkflow in bag.workflows
    assert run_experiment_enrollment_census in bag.activities
