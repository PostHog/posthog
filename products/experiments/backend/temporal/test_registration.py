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


def test_scheduled_workflows_registered_on_general_purpose_queue():
    # The canary and census schedules dispatch to the general-purpose queue; membership in
    # the product WORKFLOWS list alone registers on the recalculation queue only. A workflow
    # missing here leaves its scheduled runs retrying "not registered on this worker" forever.
    # Matches the raw queue specs by content, not by queue name: in test settings all queue
    # names alias to one value and the aggregated WORKFLOWS_DICT merges every spec together,
    # which would make a name-based assertion pass even when the registration is missing.
    from posthog.management.commands.start_temporal_worker import (  # noqa: PLC0415 — imports every product's temporal modules
        _task_queue_specs,
    )

    general_purpose_specs = [
        (workflows, activities)
        for _queue, workflows, activities in _task_queue_specs
        if any(workflow.__name__ == "DeletePersonsWorkflow" for workflow in workflows)
    ]
    assert general_purpose_specs, "general-purpose queue spec not found"
    for workflows, activities in general_purpose_specs:
        assert ExperimentPrecomputeCanaryWorkflow in workflows
        assert ExperimentPrecomputeEnrollmentCensusWorkflow in workflows
        assert run_experiment_enrollment_census in activities
