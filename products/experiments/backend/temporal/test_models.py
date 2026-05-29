from products.experiments.backend.temporal.models import (
    ExperimentMetricsRecalculationWorkflowInputs,
    ExperimentMetricToRecalculate,
    MetricRecalculationResult,
    RecalculationProgressUpdate,
)


def test_workflow_inputs_holds_recalculation_id():
    inputs = ExperimentMetricsRecalculationWorkflowInputs(recalculation_id="abc")
    assert inputs.recalculation_id == "abc"


def test_metric_to_recalculate_fields():
    metric = ExperimentMetricToRecalculate(experiment_id=1, metric_uuid="u", metric_type="primary")
    assert metric.experiment_id == 1
    assert metric.metric_uuid == "u"
    assert metric.metric_type == "primary"


def test_result_defaults():
    result = MetricRecalculationResult(metric_uuid="u", success=True)
    assert result.success is True
    assert result.error_step is None
    assert result.error_message is None


def test_progress_update_defaults():
    update = RecalculationProgressUpdate(recalculation_id="abc")
    assert update.status is None
    assert update.total_metrics is None
    assert update.metric_uuids is None
    assert update.query_to is None
    assert update.increment_completed is False
    assert update.increment_failed is False
    assert update.error_info is None
    assert update.mark_started is False
    assert update.mark_completed is False
