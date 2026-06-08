from products.experiments.backend.temporal import ACTIVITIES, WORKFLOWS


def test_activities_registered():
    names = {activity.__name__ for activity in ACTIVITIES}
    assert names == {
        "discover_experiment_metrics",
        "calculate_experiment_metric_for_recalculation",
        "update_recalculation_progress",
    }


def test_workflows_empty_until_workflow_added():
    # The workflow is added in the next PR; until then the package exposes no workflows.
    assert WORKFLOWS == []
