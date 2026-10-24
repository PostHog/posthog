"""The target sample of an experiment's running time estimate. The header of the experiment page and the health checks
read it from here, so that both show the same target.

In manual mode the target is the one the user saved from a baseline they entered. Otherwise it comes from the stored
result of the first primary metric: the variance the analysis computes from it, with CUPED when the analysis applied
CUPED, and the traffic split of the flag.
"""

from collections.abc import Mapping
from dataclasses import field

from pydantic import ValidationError

from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentQueryResponse,
    ExperimentStatsBaseValidated,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
)

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import RunningTimeMode
from products.experiments.backend.hogql_queries.utils import (
    FrequentistSettings,
    metric_variant_to_cuped_data,
    metric_variant_to_statistic,
)
from products.experiments.backend.metric_calculation.config import (
    MetricCalculationConfig,
    build_primary_calculation_configs,
    team_experiments_configs,
)
from products.experiments.backend.metric_calculation.results import MetricResultStore
from products.experiments.backend.metric_resolution import ExperimentMetric, build_metric
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.running_time_calculator import comparison_sample_size, round_up_samples
from products.experiments.backend.setup_context import PRODUCT_DEFAULT_MINIMUM_DETECTABLE_EFFECT
from products.experiments.stats.shared.cuped import cuped_adjust
from products.experiments.stats.shared.statistics import (
    ProportionStatistic,
    RatioStatistic,
    SampleMeanStatistic,
    StatisticError,
)
from products.feature_flags.backend.facade.edits import Split, parse_variants

VariantResult = ExperimentVariantResultBayesian | ExperimentVariantResultFrequentist

# A funnel's stored stats carry sample sessions per step, which can be large, and the target never reads them.
_STATS_FIELDS = set(ExperimentStatsBaseValidated.model_fields) - {"step_sessions"}


@frozen
class ComparisonVariance:
    """The variances of the control and of one variant in their comparison, as the analysis computes them."""

    control: float
    variant: float


@frozen
class RunningTimeTarget:
    # The relative effect, as a percentage, that the target sizes the experiment to detect.
    minimum_detectable_effect: float
    # The exposures across the analyzed variants that the experiment needs. None when there is no stored result yet,
    # or the result can't size a target.
    recommended_sample_size: int | None
    # The exposures so far that count toward the target: the control's and those of the variants that get traffic.
    # None in manual mode, whose saved target counts every variant, and when no stored result can size the target.
    current_sample_size: int | None = None
    # By variant key. Empty when no stored result was read, or it can't size a target.
    variances: Mapping[str, ComparisonVariance] = field(default_factory=dict)
    # The level the analysis tests at, which sizes the target.
    confidence_level: float = 0.95


@frozen
class _Comparison:
    # The variant's share of the exposures across the analyzed variants.
    share: float
    variance: ComparisonVariance
    samples: int


@frozen
class _Sizing:
    baseline_value: float
    control_share: float
    control_samples: int
    comparisons: Mapping[str, _Comparison]
    confidence_level: float

    @property
    def samples(self) -> int:
        return self.control_samples + sum(comparison.samples for comparison in self.comparisons.values())

    def sample_size(self, minimum_detectable_effect: float) -> int | None:
        difference = minimum_detectable_effect / 100 * self.baseline_value
        if difference == 0 or not self.comparisons:
            return None
        samples = round_up_samples(
            max(
                comparison_sample_size(
                    difference,
                    control_variance=comparison.variance.control,
                    variant_variance=comparison.variance.variant,
                    control_share=self.control_share,
                    variant_share=comparison.share,
                    confidence_level=self.confidence_level,
                )
                for comparison in self.comparisons.values()
            )
        )
        # The delta method can return a negative variance, and a negative sample has no meaning as a count.
        return samples if samples > 0 else None


def load_running_time_target(
    experiment: Experiment, *, minimum_detectable_effect: float | None = None, mode: RunningTimeMode | None = None
) -> RunningTimeTarget:
    """The target of the experiment's running time estimate. `minimum_detectable_effect` and `mode` replace the saved
    ones, so that the page can show the target for settings the user is still editing."""
    team_config = team_experiments_configs([experiment.team_id])[experiment.team_id]
    calculation_config = next(iter(build_primary_calculation_configs(experiment, team_config=team_config)), None)
    manual = _is_manual(experiment, mode)
    response = (
        MetricResultStore(experiment_id=experiment.id).current_response(calculation_config)
        if calculation_config is not None and not manual
        else None
    )
    return running_time_target(
        experiment,
        team_config=team_config,
        calculation_config=calculation_config,
        response=response,
        minimum_detectable_effect=minimum_detectable_effect,
        mode=mode,
    )


def running_time_target(
    experiment: Experiment,
    *,
    team_config: TeamExperimentsConfig,
    calculation_config: MetricCalculationConfig | None,
    response: ExperimentQueryResponse | None,
    minimum_detectable_effect: float | None = None,
    mode: RunningTimeMode | None = None,
) -> RunningTimeTarget:
    """The target from the first primary metric's `calculation_config` and its current stored `response`, for a
    caller that has loaded them already."""
    planned = planned_minimum_detectable_effect(experiment, team_config)
    metric = _analyzed_metric(calculation_config.definition) if calculation_config is not None else None
    confidence_level = _confidence_level(calculation_config) if calculation_config is not None else 0.95
    sizing = (
        _sizing(metric, response, parse_variants(experiment.feature_flag.variants), confidence_level)
        if metric is not None and response is not None
        else None
    )
    variances = {key: comparison.variance for key, comparison in sizing.comparisons.items()} if sizing else {}
    if _is_manual(experiment, mode):
        # The saved target was sized for the saved effect, so an effect the user is editing does not apply to it.
        return RunningTimeTarget(
            minimum_detectable_effect=planned,
            recommended_sample_size=_saved_sample_size(experiment),
            variances=variances,
            confidence_level=confidence_level,
        )
    effect = minimum_detectable_effect or planned
    return RunningTimeTarget(
        minimum_detectable_effect=effect,
        recommended_sample_size=sizing.sample_size(effect) if sizing else None,
        current_sample_size=sizing.samples if sizing else None,
        variances=variances,
        confidence_level=confidence_level,
    )


def size_target(
    *,
    metric: ExperimentMetric,
    response: ExperimentQueryResponse,
    split: Split,
    minimum_detectable_effect: float,
    confidence_level: float = 0.95,
) -> int | None:
    """The exposures across the analyzed variants that give each comparison with the control the power to detect
    `minimum_detectable_effect`, at the variances the analysis computes from `response`."""
    sizing = _sizing(metric, response, split, confidence_level)
    return sizing.sample_size(minimum_detectable_effect) if sizing else None


def _sizing(
    metric: ExperimentMetric, response: ExperimentQueryResponse, split: Split, confidence_level: float
) -> _Sizing | None:
    baseline = response.baseline
    if baseline is None or baseline.number_of_samples < 2:
        return None
    variant_results = [_as_stats(variant) for variant in response.variant_results or []]
    shares = _traffic_shares(split, baseline.key, [variant.key for variant in variant_results])
    if shares is None:
        return None
    try:
        control = metric_variant_to_statistic(metric, baseline)
        comparisons = {
            variant.key: _Comparison(
                share=shares[variant.key],
                variance=_comparison_variance(metric, control, baseline, variant),
                samples=variant.number_of_samples,
            )
            for variant in variant_results
            if variant.key in shares
        }
    except StatisticError:
        return None
    return _Sizing(
        baseline_value=_value(control),
        control_share=shares[baseline.key],
        control_samples=baseline.number_of_samples,
        comparisons=comparisons,
        confidence_level=confidence_level,
    )


def _confidence_level(calculation_config: MetricCalculationConfig) -> float:
    stats = calculation_config.settings.stats
    return 1 - stats.alpha if isinstance(stats, FrequentistSettings) else stats.ci_level


def planned_minimum_detectable_effect(experiment: Experiment, team_config: TeamExperimentsConfig) -> float:
    planned = _running_time_calculation(experiment).get("minimum_detectable_effect")
    if isinstance(planned, int | float) and not isinstance(planned, bool) and planned > 0:
        return float(planned)
    return float(team_config.default_minimum_detectable_effect or PRODUCT_DEFAULT_MINIMUM_DETECTABLE_EFFECT)


def is_manual_running_time(experiment: Experiment) -> bool:
    estimate_config = _running_time_calculation(experiment).get("exposure_estimate_config")
    return (
        isinstance(estimate_config, dict) and estimate_config.get("conversionRateInputType") == RunningTimeMode.MANUAL
    )


def _is_manual(experiment: Experiment, mode: RunningTimeMode | None) -> bool:
    return mode == RunningTimeMode.MANUAL if mode is not None else is_manual_running_time(experiment)


def _saved_sample_size(experiment: Experiment) -> int | None:
    saved = _running_time_calculation(experiment).get("recommended_sample_size")
    if isinstance(saved, int | float) and not isinstance(saved, bool) and saved > 0:
        return int(saved)
    return None


def _running_time_calculation(experiment: Experiment) -> dict:
    return experiment.running_time_calculation if isinstance(experiment.running_time_calculation, dict) else {}


def _comparison_variance(
    metric: ExperimentMetric,
    control: SampleMeanStatistic | ProportionStatistic | RatioStatistic,
    baseline: ExperimentStatsBaseValidated,
    variant: ExperimentStatsBaseValidated,
) -> ComparisonVariance:
    # A variant with fewer than 2 samples has no spread of its own yet, so the plan takes the control's.
    if variant.number_of_samples < 2:
        return ComparisonVariance(control=control.variance, variant=control.variance)
    treatment = metric_variant_to_statistic(metric, variant)
    # The analysis applies CUPED only to mean and funnel metrics, and the stored stats carry the covariate only when
    # it did. Its adjustment pools the control with each variant, so each comparison has its own pair of variances.
    if (
        isinstance(metric, ExperimentMeanMetric | ExperimentFunnelMetric)
        and isinstance(control, SampleMeanStatistic | ProportionStatistic)
        and isinstance(treatment, SampleMeanStatistic | ProportionStatistic)
        and baseline.covariate_sum is not None
        and variant.covariate_sum is not None
    ):
        adjusted = cuped_adjust(
            treatment, control, metric_variant_to_cuped_data(variant), metric_variant_to_cuped_data(baseline)
        )
        return ComparisonVariance(
            control=adjusted.control_adjusted.variance, variant=adjusted.treatment_adjusted.variance
        )
    return ComparisonVariance(control=control.variance, variant=treatment.variance)


def _traffic_shares(split: Split, control_key: str, variant_keys: list[str]) -> dict[str, float] | None:
    """Each analyzed variant's share of the exposures, for the variants that get traffic, with the control first.
    Equal shares when the flag has no readable percentage for one of them. None when no comparison with the control
    can get a sample."""
    percentages = {variant.key: variant.rollout_percentage for variant in split if variant.key}
    keys = [control_key, *variant_keys]
    if any(percentages.get(key) is None for key in keys):
        return dict.fromkeys(keys, 1 / len(keys)) if variant_keys else None
    # A variant at 0% gets no exposures, so no comparison with it can reach any sample.
    served = {key: float(percentages[key] or 0) for key in keys if (percentages[key] or 0) > 0}
    if control_key not in served or len(served) < 2:
        return None
    total = sum(served.values())
    return {key: percentage / total for key, percentage in served.items()}


def _value(statistic: SampleMeanStatistic | ProportionStatistic | RatioStatistic) -> float:
    if isinstance(statistic, SampleMeanStatistic):
        return statistic.mean
    if isinstance(statistic, ProportionStatistic):
        return statistic.proportion
    return statistic.ratio


def _analyzed_metric(definition: dict) -> ExperimentMetric | None:
    # The parse the analysis runs, so that a metric it can't compute gets no target.
    try:
        return build_metric(definition)
    except (KeyError, TypeError, ValidationError):
        return None


def _as_stats(variant: VariantResult) -> ExperimentStatsBaseValidated:
    return ExperimentStatsBaseValidated.model_validate(variant.model_dump(include=_STATS_FIELDS))
