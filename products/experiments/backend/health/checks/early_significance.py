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
)
from products.experiments.backend.health.context import HealthContext, StoredMetricResult, StoredVariantResult
from products.experiments.backend.health.skips import (
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    RUNS_AFTER_LAUNCH,
    CheckSkip,
    not_applicable,
    not_checked,
)
from products.experiments.backend.running_time_calculator import calculate_detectable_effect, calculate_sample_size

# pinned: sent as `finding_variant` on the health finding events.
BELOW_DETECTABLE_EFFECT = "below_detectable_effect"

# The results page shows results from 50 exposures (`EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS` in
# products/experiments/frontend/constants.ts). Keep the two in step, so that the note never names a result the page hides.
MIN_SAMPLES_FOR_RESULTS = 50


@frozen
class _Comparison:
    variant: StoredVariantResult
    # Relative to the control, as percentages.
    observed: float
    detectable: float


def early_significance_skip(ctx: HealthContext) -> CheckSkip | None:
    if ctx.archived:
        return not_applicable(NOT_ON_ARCHIVED)
    if not ctx.is_launched:
        return not_applicable(RUNS_AFTER_LAUNCH)
    # After the end the decision is made, and "wait for the planned sample" can't be followed.
    if ctx.has_ended:
        return not_applicable(NOT_AFTER_END)
    if ctx.primary_metric_count == 0:
        return not_applicable("Runs once the experiment has a primary metric")
    metric = ctx.primary_metric
    if metric is None:
        return not_checked("Couldn't read the results of the primary metric")
    if not metric.is_funnel:
        return not_applicable("Runs on funnel primary metrics only")
    if metric.result is None:
        return not_applicable("Runs once the primary metric has results")
    if _total_samples(metric.result) < MIN_SAMPLES_FOR_RESULTS:
        return not_applicable("Runs once enough users are exposed")
    if not 0 < _control_rate(metric.result) < 1:
        return not_applicable("Runs once the control group's conversion rate is above 0% and below 100%")
    return None


def early_significance(ctx: HealthContext) -> ExperimentHealthFinding | None:
    metric = ctx.primary_metric
    if early_significance_skip(ctx) is not None or metric is None or metric.result is None:
        return None
    result = metric.result
    comparisons = _comparisons(result)
    # When every comparison detects the planned effect, the sample has reached the plan.
    if not comparisons or max(comparison.detectable for comparison in comparisons) <= metric.minimum_detectable_effect:
        return None
    below_detectable = [
        comparison
        for comparison in comparisons
        if comparison.variant.significant is True and abs(comparison.observed) < comparison.detectable
    ]
    if not below_detectable:
        return None
    comparison = min(
        below_detectable,
        key=lambda comparison: (abs(comparison.observed) / comparison.detectable, comparison.variant.key),
    )

    samples = _total_samples(result)
    # The running-time estimate counts the variants of the flag.
    number_of_variants = len(ctx.flag.variants) if ctx.flag and ctx.flag.variants else len(result.variants) + 1
    planned_samples = calculate_sample_size(
        "funnel", _control_rate(result), metric.minimum_detectable_effect, number_of_variants
    )
    sentences = [
        f'The variant "{comparison.variant.key}" shows a {comparison.observed:+.0f}% difference on the metric '
        f'"{metric.name}", which is significant.',
        f"With {samples:,} users so far, the experiment can reliably detect differences of about "
        f"{comparison.detectable:.0f}% or more, so this difference may shrink or go away as more users arrive.",
    ]
    if planned_samples:
        sentences += [
            f"The running time estimate needs about {planned_samples:,} users to detect a "
            f"{metric.minimum_detectable_effect:g}% difference.",
            "Wait for that sample before you decide.",
        ]
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.EARLY_SIGNIFICANCE,
        subcode=BELOW_DETECTABLE_EFFECT,
        severity=ExperimentHealthFindingSeverity.INFO,
        title="Significant result on a small sample",
        detail=" ".join(sentences),
        evidence={
            "variant": comparison.variant.key,
            "observed_effect": round(comparison.observed, 1),
            "detectable_effect": round(comparison.detectable, 1),
            "minimum_detectable_effect": metric.minimum_detectable_effect,
            "samples": samples,
            "planned_samples": planned_samples,
        },
        actions=(),
        diagnostic_ref=None,
    )


def _comparisons(result: StoredMetricResult) -> list[_Comparison]:
    control_rate = _control_rate(result)
    comparisons: list[_Comparison] = []
    for variant in result.variants:
        detectable = calculate_detectable_effect("funnel", control_rate, result.baseline_samples, variant.samples)
        if detectable is not None:
            rate = variant.sum / variant.samples
            comparisons.append(
                _Comparison(variant=variant, observed=100 * (rate / control_rate - 1), detectable=detectable)
            )
    return comparisons


def _total_samples(result: StoredMetricResult) -> int:
    return result.baseline_samples + sum(variant.samples for variant in result.variants)


def _control_rate(result: StoredMetricResult) -> float:
    return result.baseline_sum / result.baseline_samples if result.baseline_samples > 0 else 0.0
