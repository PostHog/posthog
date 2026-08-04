"""
Analysis-health signals for experiments. Pure functions — no I/O.

Currently evaluates one signal: asymmetric `$multiple`-exclusion bias on uneven
splits. Designed to grow (SRM, low exposures, variant drift, ...) as additional
pure evaluators when needed.
"""

from posthog.schema import BiasRisk, MultipleVariantHandling

from products.experiments.backend.variant_distribution import is_evenly_distributed

MULTIPLE_VARIANT_KEY = "$multiple"

# `$multiple` share above this triggers the warning. Below this, the asymmetric-
# exclusion effect on arm means is too small to matter in practice.
MULTIPLE_VARIANT_BIAS_THRESHOLD = 0.1  # on the 0-100 scale (0.1 = 0.1%)

# Minimum observed exposures required in the smallest variant arm before the bias
# percentage means anything. The exclusion bias lands on the smaller arm specifically,
# so gating on the total (the way SRM_MINIMUM_SAMPLE_SIZE does) isn't enough: a total
# that clears a low bar can still hide a tiny smaller arm where a single `$multiple`
# exclusion swings the percentage past the threshold on noise alone.
MIN_SMALLER_ARM_EXPOSURES_FOR_BIAS_RISK = 100


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

    arm_exposures = {key: count for key, count in total_exposures.items() if key != MULTIPLE_VARIANT_KEY}
    if not arm_exposures or min(arm_exposures.values()) < MIN_SMALLER_ARM_EXPOSURES_FOR_BIAS_RISK:
        return None

    total_observed = sum(total_exposures.values())
    multiple_observed = total_exposures.get(MULTIPLE_VARIANT_KEY, 0)
    multiple_variant_percentage = (multiple_observed / total_observed) * 100
    if multiple_variant_percentage <= MULTIPLE_VARIANT_BIAS_THRESHOLD:
        return None

    return BiasRisk(multiple_variant_percentage=multiple_variant_percentage)
