"""
A significant result that is smaller than the effect the sample can detect, before the sample reaches the plan. Pure
functions, no I/O.

On a small sample, a difference that reaches significance by chance is larger than the real one, so such a result often
shrinks or goes away as more users arrive. A large difference is reliable on a small sample too, so the check compares
the observed difference with the smallest one the sample can detect, by the running-time estimate's formula.
"""

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthValueKey,
)
from products.experiments.backend.health.context import HealthContext, PrimaryMetric
from products.experiments.backend.health.skips import (
    NEEDS_EXPOSURES,
    NEEDS_PRIMARY_METRIC,
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    CheckRows,
    CheckSkip,
    CheckValues,
    not_applicable,
    not_checked,
)
from products.experiments.backend.logic.result_stats import MetricResultStats, VariantStats
from products.experiments.backend.running_time_calculator import calculate_detectable_effect
from products.experiments.backend.running_time_target import RunningTimeTarget

# pinned: sent as `finding_subcode` on the health finding events.
BELOW_DETECTABLE_EFFECT = "below_detectable_effect"

# The results page shows results from 50 exposures (`EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS` in
# products/experiments/frontend/constants.ts). Keep the two in step, so that the note never names a result the page hides.
MIN_SAMPLES_FOR_RESULTS = 50


@frozen
class _Comparison:
    variant: VariantStats
    # Relative to the control, as percentages.
    observed: float
    detectable: float
    significant: bool


@frozen
class _Readout:
    metric: PrimaryMetric
    samples: int
    planned_samples: int | None
    comparisons: tuple[_Comparison, ...]


def early_significance_values(ctx: HealthContext) -> CheckValues:
    readout = _significant_readout(ctx)
    if readout is None:
        return {}
    return {
        ExperimentHealthValueKey.METRIC_NAME: readout.metric.name,
        ExperimentHealthValueKey.SAMPLE_COUNT: readout.samples,
        ExperimentHealthValueKey.PLANNED_SAMPLE_COUNT: readout.planned_samples,
    }


def early_significance_rows(ctx: HealthContext) -> CheckRows:
    readout = _significant_readout(ctx)
    if readout is None:
        return ()
    return tuple(
        {
            ExperimentHealthValueKey.VARIANT: comparison.variant.key,
            ExperimentHealthValueKey.DIFFERENCE_PERCENTAGE: round(comparison.observed, 1),
            ExperimentHealthValueKey.DETECTABLE_DIFFERENCE_PERCENTAGE: round(comparison.detectable, 1),
            ExperimentHealthValueKey.SIGNIFICANT: comparison.significant,
        }
        for comparison in readout.comparisons
    )


def _significant_readout(ctx: HealthContext) -> _Readout | None:
    """The comparisons that the check reads, when a variant is significant. Without a significant variant the running
    time estimate already shows the progress, so the check shows nothing."""
    readout = _readout(ctx)
    if isinstance(readout, CheckSkip) or not any(comparison.significant for comparison in readout.comparisons):
        return None
    return readout


def _readout(ctx: HealthContext) -> _Readout | CheckSkip:
    """The sample and the comparison of each variant with the control, or why the check doesn't look."""
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    if not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    # After the end the decision is made, and "wait for the planned sample" can't be followed.
    if ctx.has_ended:
        return not_applicable(NOT_AFTER_END)
    if ctx.primary_metric_count == 0:
        return not_applicable(NEEDS_PRIMARY_METRIC)
    metric = ctx.primary_metric
    if metric is None:
        return not_checked("Couldn't read the results of the primary metric")
    if not metric.is_funnel:
        return not_applicable("Runs on funnel primary metrics only")
    result = metric.result
    if result is None:
        return not_applicable("Runs once the primary metric has results")
    samples = _total_samples(result)
    if samples < MIN_SAMPLES_FOR_RESULTS:
        return not_applicable(NEEDS_EXPOSURES)
    control_rate = result.baseline.mean or 0
    if not 0 < control_rate < 1:
        return not_applicable("Runs once the control group's conversion rate is above 0% and below 100%")
    # The running time estimate's "Target reached" compares the same total, so the note and the estimate agree.
    if metric.target.current_sample_size is not None:
        samples = metric.target.current_sample_size
    return _Readout(
        metric=metric,
        samples=samples,
        planned_samples=metric.target.recommended_sample_size,
        comparisons=tuple(_comparisons(result, control_rate, metric.target)),
    )


def early_significance(ctx: HealthContext) -> CheckOutcome:
    readout = _readout(ctx)
    if isinstance(readout, CheckSkip):
        return readout
    metric, samples, planned_samples = readout.metric, readout.samples, readout.planned_samples
    if planned_samples is None or samples >= planned_samples:
        return None
    below_detectable = [
        comparison
        for comparison in readout.comparisons
        if comparison.significant and abs(comparison.observed) < comparison.detectable
    ]
    if not below_detectable:
        return None
    comparison = min(
        below_detectable,
        key=lambda comparison: (abs(comparison.observed) / comparison.detectable, comparison.variant.key),
    )
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.EARLY_SIGNIFICANCE,
        subcode=BELOW_DETECTABLE_EFFECT,
        severity=ExperimentHealthFindingSeverity.INFO,
        title="Significant result on a small sample",
        detail=" ".join(
            [
                f'The variant "{comparison.variant.key}" shows a {comparison.observed:+.0f}% difference on the metric '
                f'"{metric.name}", which is significant.',
                f"With {samples:,} users so far, the experiment can reliably detect differences of about "
                f"{comparison.detectable:.0f}% or more, so this difference may shrink or go away as more users arrive.",
                f"The running time estimate needs about {planned_samples:,} users to detect a "
                f"{metric.target.minimum_detectable_effect:g}% difference.",
                "Wait for that sample before you decide.",
            ]
        ),
        evidence={
            "variant": comparison.variant.key,
            "observed_effect": round(comparison.observed, 1),
            "detectable_effect": round(comparison.detectable, 1),
            "minimum_detectable_effect": metric.target.minimum_detectable_effect,
            "samples": samples,
            "planned_samples": planned_samples,
        },
        actions=(),
        diagnostic_ref=None,
    )


def _comparisons(result: MetricResultStats, control_rate: float, target: RunningTimeTarget) -> list[_Comparison]:
    comparisons: list[_Comparison] = []
    for variant in result.variants:
        if variant.interval is None:
            continue
        # The variances and the level that the running time target uses, so CUPED applies here too. Without the
        # variances, p(1-p) of the control.
        variance = target.variances.get(variant.key)
        detectable = calculate_detectable_effect(
            "funnel",
            control_rate,
            result.baseline.number_of_samples,
            variant.number_of_samples,
            variance=variance.control if variance else None,
            variant_variance=variance.variant if variance else None,
            confidence_level=target.confidence_level,
        )
        if detectable is not None:
            # The difference the results page shows, from the analysis itself, so CUPED and the Bayesian model apply.
            comparisons.append(
                _Comparison(
                    variant=variant,
                    observed=100 * variant.interval.midpoint,
                    detectable=detectable,
                    significant=variant.significant is True,
                )
            )
    return comparisons


def _total_samples(result: MetricResultStats) -> int:
    return result.baseline.number_of_samples + sum(variant.number_of_samples for variant in result.variants)
