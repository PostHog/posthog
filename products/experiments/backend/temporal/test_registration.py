from products.experiments.backend.temporal import ACTIVITIES, WORKFLOWS
from products.experiments.backend.temporal.recalculation_workflow import ExperimentMetricsRecalculationWorkflow


def test_activities_registered():
    names = {activity.__name__ for activity in ACTIVITIES}
    assert names == {
        "discover_experiment_metrics",
        "calculate_experiment_metric_for_recalculation",
        "update_recalculation_progress",
    }


def test_workflow_registered():
    assert WORKFLOWS == [ExperimentMetricsRecalculationWorkflow]
