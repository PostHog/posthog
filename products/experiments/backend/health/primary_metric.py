from posthog.exceptions_capture import capture_exception

from products.experiments.backend.health.context import PrimaryMetric
from products.experiments.backend.metric_calculation.config import (
    MetricCalculationConfig,
    build_primary_calculation_configs,
    team_experiments_configs,
)
from products.experiments.backend.metric_calculation.results import MetricResultStore
from products.experiments.backend.metric_resolution import saved_metric_links
from products.experiments.backend.metric_utils import get_default_metric_title
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.setup_context import PRODUCT_DEFAULT_MINIMUM_DETECTABLE_EFFECT


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
    return PrimaryMetric(
        name=_metric_name(experiment, calculation_config),
        is_funnel=is_funnel,
        minimum_detectable_effect=_minimum_detectable_effect(experiment, team_config),
        manual_running_time=_manual_running_time(experiment),
        result=MetricResultStore(experiment_id=experiment.id).current_result(calculation_config) if is_funnel else None,
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


def _minimum_detectable_effect(experiment: Experiment, team_config: TeamExperimentsConfig) -> float:
    running_time_calculation = experiment.running_time_calculation
    planned = (
        running_time_calculation.get("minimum_detectable_effect")
        if isinstance(running_time_calculation, dict)
        else None
    )
    if isinstance(planned, int | float) and not isinstance(planned, bool) and planned > 0:
        return float(planned)
    return float(team_config.default_minimum_detectable_effect or PRODUCT_DEFAULT_MINIMUM_DETECTABLE_EFFECT)


def _manual_running_time(experiment: Experiment) -> bool:
    # pinned: the page's `ConversionRateInputType.MANUAL` in frontend/src/types.ts, read by `runningTimeLogic`.
    running_time_calculation = experiment.running_time_calculation
    estimate_config = (
        running_time_calculation.get("exposure_estimate_config") if isinstance(running_time_calculation, dict) else None
    )
    return isinstance(estimate_config, dict) and estimate_config.get("conversionRateInputType") == "manual"
