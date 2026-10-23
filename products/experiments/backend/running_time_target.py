"""The target sample of an experiment's running time estimate. The header of the experiment page and the health checks
read it from here, so that both show the same target.

In manual mode the target is the one the user saved from a baseline they entered. Otherwise it comes from the stored
result of the first primary metric: the variance the analysis computes from it, with CUPED when the analysis applied
CUPED, and the traffic split of the flag.
"""

from pydantic import ValidationError

from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetric,
    ExperimentQueryResponse,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    ExperimentStatsBaseValidated,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
)

from posthog.dataclasses import frozen

from products.experiments.backend.hogql_queries.utils import metric_variant_to_cuped_data, metric_variant_to_statistic
from products.experiments.backend.metric_calculation.config import (
    MetricCalculationConfig,
    build_primary_calculation_configs,
    team_experiments_configs,
)
from products.experiments.backend.metric_calculation.results import MetricResultStore
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.running_time_calculator import CalculatorMetricType, calculate_sample_size
from products.experiments.backend.setup_context import PRODUCT_DEFAULT_MINIMUM_DETECTABLE_EFFECT
from products.experiments.stats.shared.cuped import cuped_adjust
from products.experiments.stats.shared.statistics import (
    ProportionStatistic,
    RatioStatistic,
    SampleMeanStatistic,
    StatisticError,
)
from products.feature_flags.backend.facade.edits import Split, parse_variants

AnalyzedMetric = ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | ExperimentRetentionMetric
VariantResult = ExperimentVariantResultBayesian | ExperimentVariantResultFrequentist

_STATS_FIELDS = set(ExperimentStatsBaseValidated.model_fields)


@frozen
class RunningTimeTarget:
    # The relative effect, as a percentage, that the target sizes the experiment to detect.
    minimum_detectable_effect: float
    # The exposures across the analyzed variants that the experiment needs. None when there is no stored result yet,
    # or the result can't size a target.
    recommended_sample_size: int | None


def load_running_time_target(
    experiment: Experiment, *, minimum_detectable_effect: float | None = None
) -> RunningTimeTarget:
    """The target of the experiment's running time estimate. `minimum_detectable_effect` replaces the saved one, so
    that the page can show the target for an effect the user is still editing."""
    team_config = team_experiments_configs([experiment.team_id])[experiment.team_id]
    calculation_config = next(iter(build_primary_calculation_configs(experiment, team_config=team_config)), None)
    response = (
        MetricResultStore(experiment_id=experiment.id).current_response(calculation_config)
        if calculation_config is not None and not is_manual_running_time(experiment)
        else None
    )
    return running_time_target(
        experiment,
        team_config=team_config,
        calculation_config=calculation_config,
        response=response,
        minimum_detectable_effect=minimum_detectable_effect,
    )


def running_time_target(
    experiment: Experiment,
    *,
    team_config: TeamExperimentsConfig,
    calculation_config: MetricCalculationConfig | None,
    response: ExperimentQueryResponse | None,
    minimum_detectable_effect: float | None = None,
) -> RunningTimeTarget:
    """The target from the first primary metric's `calculation_config` and its current stored `response`, for a
    caller that has loaded them already."""
    effect = minimum_detectable_effect or planned_minimum_detectable_effect(experiment, team_config)
    if is_manual_running_time(experiment):
        return RunningTimeTarget(
            minimum_detectable_effect=effect, recommended_sample_size=_saved_sample_size(experiment)
        )
    metric = _analyzed_metric(calculation_config.definition) if calculation_config is not None else None
    recommended_sample_size = (
        size_target(
            metric=metric,
            response=response,
            split=parse_variants(experiment.feature_flag.variants),
            minimum_detectable_effect=effect,
        )
        if metric is not None and response is not None
        else None
    )
    return RunningTimeTarget(minimum_detectable_effect=effect, recommended_sample_size=recommended_sample_size)


def size_target(
    *, metric: AnalyzedMetric, response: ExperimentQueryResponse, split: Split, minimum_detectable_effect: float
) -> int | None:
    """The exposures across the analyzed variants that give each comparison with the control the power to detect
    `minimum_detectable_effect`, at the variance of the control in `response`."""
    baseline = response.baseline
    if baseline is None or baseline.number_of_samples < 2:
        return None
    shares = _traffic_shares(split, baseline.key, [variant.key for variant in response.variant_results or []])
    if shares is None:
        return None
    served = [_as_stats(variant) for variant in response.variant_results or [] if variant.key in shares]
    try:
        control = metric_variant_to_statistic(metric, baseline)
        variance = max(
            [
                _control_variance(metric, control, baseline, variant)
                for variant in served
                if variant.number_of_samples >= 2
            ],
            default=control.variance,
        )
    except StatisticError:
        return None
    return calculate_sample_size(
        _calculator_metric_type(metric),
        _value(control),
        minimum_detectable_effect,
        number_of_variants=len(shares),
        variance=variance,
        split=list(shares.values()),
    )


def planned_minimum_detectable_effect(experiment: Experiment, team_config: TeamExperimentsConfig) -> float:
    planned = _running_time_calculation(experiment).get("minimum_detectable_effect")
    if isinstance(planned, int | float) and not isinstance(planned, bool) and planned > 0:
        return float(planned)
    return float(team_config.default_minimum_detectable_effect or PRODUCT_DEFAULT_MINIMUM_DETECTABLE_EFFECT)


def is_manual_running_time(experiment: Experiment) -> bool:
    # pinned: the page's `ConversionRateInputType.MANUAL` in frontend/src/types.ts, read by `runningTimeLogic`.
    estimate_config = _running_time_calculation(experiment).get("exposure_estimate_config")
    return isinstance(estimate_config, dict) and estimate_config.get("conversionRateInputType") == "manual"


def _saved_sample_size(experiment: Experiment) -> int | None:
    saved = _running_time_calculation(experiment).get("recommended_sample_size")
    if isinstance(saved, int | float) and not isinstance(saved, bool) and saved > 0:
        return int(saved)
    return None


def _running_time_calculation(experiment: Experiment) -> dict:
    return experiment.running_time_calculation if isinstance(experiment.running_time_calculation, dict) else {}


def _control_variance(
    metric: AnalyzedMetric,
    control: SampleMeanStatistic | ProportionStatistic | RatioStatistic,
    baseline: ExperimentStatsBaseValidated,
    variant: ExperimentStatsBaseValidated,
) -> float:
    # The analysis applies CUPED only to mean and funnel metrics, and the stored stats carry the covariate only when
    # it did. Its adjustment pools the control with each variant, so each comparison has its own variance. The
    # largest one sizes the target.
    if (
        isinstance(metric, ExperimentMeanMetric | ExperimentFunnelMetric)
        and isinstance(control, SampleMeanStatistic | ProportionStatistic)
        and baseline.covariate_sum is not None
        and variant.covariate_sum is not None
    ):
        treatment = metric_variant_to_statistic(metric, variant)
        if isinstance(treatment, SampleMeanStatistic | ProportionStatistic):
            return cuped_adjust(
                treatment, control, metric_variant_to_cuped_data(variant), metric_variant_to_cuped_data(baseline)
            ).control_adjusted.variance
    return control.variance


def _traffic_shares(split: Split, control_key: str, variant_keys: list[str]) -> dict[str, float] | None:
    """The flag's percentage of each analyzed variant that gets traffic, with the control first. Equal shares when the
    flag has no readable percentage for one of them. None when no comparison with the control can get a sample."""
    percentages = {variant.key: variant.rollout_percentage for variant in split if variant.key}
    keys = [control_key, *variant_keys]
    if any(percentages.get(key) is None for key in keys):
        return dict.fromkeys(keys, 1.0) if variant_keys else None
    # A variant at 0% gets no exposures, so no comparison with it can reach any sample.
    served = {key: float(percentages[key] or 0) for key in variant_keys if (percentages[key] or 0) > 0}
    control = float(percentages[control_key] or 0)
    if control <= 0 or not served:
        return None
    return {control_key: control, **served}


def _value(statistic: SampleMeanStatistic | ProportionStatistic | RatioStatistic) -> float:
    if isinstance(statistic, SampleMeanStatistic):
        return statistic.mean
    if isinstance(statistic, ProportionStatistic):
        return statistic.proportion
    return statistic.ratio


def _calculator_metric_type(metric: AnalyzedMetric) -> CalculatorMetricType:
    if isinstance(metric, ExperimentFunnelMetric):
        return "funnel"
    if isinstance(metric, ExperimentRatioMetric):
        return "ratio"
    if isinstance(metric, ExperimentRetentionMetric):
        return "retention"
    return "mean_count"


def _analyzed_metric(definition: dict) -> AnalyzedMetric | None:
    try:
        return ExperimentMetric.model_validate(definition).root
    except ValidationError:
        return None


def _as_stats(variant: VariantResult) -> ExperimentStatsBaseValidated:
    return ExperimentStatsBaseValidated.model_validate(variant.model_dump(include=_STATS_FIELDS))
