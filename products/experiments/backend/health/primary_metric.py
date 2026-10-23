from posthog.exceptions_capture import capture_exception

from products.experiments.backend.health.context import PrimaryMetric
from products.experiments.backend.logic.result_stats import MetricResultStats
from products.experiments.backend.metric_calculation.config import (
    MetricCalculationConfig,
    build_primary_calculation_configs,
    team_experiments_configs,
)
from products.experiments.backend.metric_calculation.results import MetricResultStore
from products.experiments.backend.metric_resolution import saved_metric_links
from products.experiments.backend.metric_utils import get_default_metric_title
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.running_time_target import running_time_target


def load_primary_metric(experiment: Experiment) -> PrimaryMetric | None:
    """
    The first primary metric of a launched experiment with its current stored result, or None. Never raises: the
    checks that read it then report that they couldn't check.
    """
    if not experiment.is_launched:
        return None
    try:
        return _load_primary_metric(experiment)
    except Exception as error:
        capture_exception(error)
        return None


def _load_primary_metric(experiment: Experiment) -> PrimaryMetric | None:
    team_config = team_experiments_configs([experiment.team_id])[experiment.team_id]
    calculation_config = next(iter(build_primary_calculation_configs(experiment, team_config=team_config)), None)
    if calculation_config is None:
        return None
    is_funnel = calculation_config.definition.get("metric_type") == "funnel"
    response = MetricResultStore(experiment_id=experiment.id).current_response(calculation_config)
    return PrimaryMetric(
        name=_metric_name(experiment, calculation_config),
        is_funnel=is_funnel,
        target=running_time_target(
            experiment, team_config=team_config, calculation_config=calculation_config, response=response
        ),
        result=MetricResultStats.from_response(response) if is_funnel and response is not None else None,
    )


def _metric_name(experiment: Experiment, calculation_config: MetricCalculationConfig) -> str:
    definition = calculation_config.definition
    # An inline metric wins over a saved metric with the same uuid, as in `get_metrics_for_calculation`.
    inline_uuids = {metric.get("uuid") for metric in experiment.metrics or [] if isinstance(metric, dict)}
    if calculation_config.metric_id not in inline_uuids:
        for link in saved_metric_links(experiment):
            query = link.saved_metric.query
            if isinstance(query, dict) and query.get("uuid") == calculation_config.metric_id:
                return link.saved_metric.name
    return definition.get("name") or get_default_metric_title(definition)
