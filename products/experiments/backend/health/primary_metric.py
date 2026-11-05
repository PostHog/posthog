from posthog.exceptions_capture import capture_exception

from products.experiments.backend.health.context import PrimaryMetric
from products.experiments.backend.logic.result_stats import MetricResultStats
from products.experiments.backend.metric_calculation.config import (
    build_primary_calculation_configs,
    calculation_metric_name,
    team_experiments_configs,
)
from products.experiments.backend.metric_calculation.results import MetricResultStore
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
        name=calculation_metric_name(experiment, calculation_config),
        is_funnel=is_funnel,
        target=running_time_target(
            experiment, team_config=team_config, calculation_config=calculation_config, response=response
        ),
        result=MetricResultStats.from_response(response) if is_funnel and response is not None else None,
    )
