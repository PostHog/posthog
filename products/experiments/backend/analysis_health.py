"""
Analysis-health signals for experiments. Pure functions — no I/O.

Evaluates asymmetric `$multiple`-exclusion bias on uneven splits, and funnel
metrics too narrow to power a result. Designed to grow (SRM, variant drift, ...)
as additional pure evaluators when needed.
"""

from posthog.schema import BiasRisk, ExperimentStatsBaseValidated, FunnelPowerRisk, MultipleVariantHandling

from products.experiments.backend.running_time_calculator import calculate_sample_size
from products.experiments.backend.variant_distribution import is_evenly_distributed

MULTIPLE_VARIANT_KEY = "$multiple"

# `$multiple` share above this triggers the warning. Below this, the asymmetric-
# exclusion effect on arm means is too small to matter in practice.
MULTIPLE_VARIANT_BIAS_THRESHOLD = 0.1  # on the 0-100 scale (0.1 = 0.1%)

# A funnel step retaining less than this share of exposed users leaves the metric with a
# relative variance large enough to drown the effects the results view displays.
NARROW_FUNNEL_STEP_THRESHOLD = 0.15

# Used when neither the experiment nor the environment sets one. Mirrors the frontend
# running-time calculator's `DEFAULT_MDE`.
DEFAULT_MINIMUM_DETECTABLE_EFFECT = 30


def evaluate_bias_risk(
    flag_variants: list[dict] | None,
    multiple_variant_handling: MultipleVariantHandling,
    total_exposures: dict[str, int],
) -> BiasRisk | None:
    """
    Empirically observed multi-variant exclusion bias risk: uneven split + EXCLUDE
    handling + observed `$multiple` share above the threshold.
    Returns a `BiasRisk` only when all three conditions hold; `None` otherwise.
    """
    if multiple_variant_handling != MultipleVariantHandling.EXCLUDE:
        return None

    variants = flag_variants or []
    if not variants:
        return None

    rollout_percentages = [variant.get("rollout_percentage", 0) for variant in variants]
    if is_evenly_distributed(rollout_percentages):
        return None

    total_observed = sum(total_exposures.values())
    if total_observed <= 0:
        return None

    multiple_observed = total_exposures.get(MULTIPLE_VARIANT_KEY, 0)
    multiple_variant_percentage = (multiple_observed / total_observed) * 100
    if multiple_variant_percentage <= MULTIPLE_VARIANT_BIAS_THRESHOLD:
        return None

    return BiasRisk(multiple_variant_percentage=multiple_variant_percentage)


def evaluate_funnel_power_risk(
    baseline: ExperimentStatsBaseValidated,
    total_exposures: int,
    number_of_variants: int,
    minimum_detectable_effect: float,
) -> FunnelPowerRisk | None:
    """
    A funnel metric is measured over everyone exposed, not over everyone who reached step
    one, so a step that keeps only a sliver of exposures turns the metric into a
    low-conversion binomial whose noise band swallows the deltas the results view shows.

    Fires when a step before the final one retains less than
    `NARROW_FUNNEL_STEP_THRESHOLD` of exposures *and* observed exposures are short of the
    sample size needed to detect `minimum_detectable_effect` at the baseline conversion
    rate. Both conditions are required: a narrow funnel with enough data can still resolve
    a result, and every young experiment is briefly short of its recommended sample size.
    """
    step_counts = baseline.step_counts
    exposures = baseline.number_of_samples
    if not step_counts or len(step_counts) < 2 or exposures <= 0:
        return None

    narrowest_index = min(range(len(step_counts) - 1), key=lambda i: step_counts[i])
    narrowest_share = step_counts[narrowest_index] / exposures
    if narrowest_share >= NARROW_FUNNEL_STEP_THRESHOLD:
        return None

    conversion_rate = step_counts[-1] / exposures
    if not 0 < conversion_rate < 1:
        return None

    recommended_sample_size = calculate_sample_size(
        "funnel", conversion_rate, minimum_detectable_effect, number_of_variants
    )
    if recommended_sample_size is None or total_exposures >= recommended_sample_size:
        return None

    return FunnelPowerRisk(
        narrowest_step=narrowest_index + 1,
        narrowest_step_percentage=narrowest_share * 100,
        observed_exposures=total_exposures,
        recommended_sample_size=recommended_sample_size,
        minimum_detectable_effect=minimum_detectable_effect,
    )
