"""
Analysis-health signals for experiments. Pure functions — no I/O.

Currently evaluates one signal: `$multiple`-exclusion bias under EXCLUDE handling.
Designed to grow (SRM, low exposures, variant drift, ...) as additional pure
evaluators when needed.
"""

from posthog.schema import BiasRisk, MultipleVariantHandling, MultiVariantBiasKind

from products.experiments.backend.variant_distribution import is_evenly_distributed

MULTIPLE_VARIANT_KEY = "$multiple"

# `$multiple` share above this triggers the warning. Below this, the exclusion
# effect on arm means is too small to matter in practice.
MULTIPLE_VARIANT_BIAS_THRESHOLD = 0.1  # on the 0-100 scale (0.1 = 0.1%)


def evaluate_bias_risk(
    flag_variants: list[dict] | None,
    multiple_variant_handling: MultipleVariantHandling,
    total_exposures: dict[str, int],
) -> BiasRisk | None:
    """
    Multi-variant exclusion bias risk: EXCLUDE handling drops every `$multiple`
    user from the results. Returns a `BiasRisk` when the observed `$multiple`
    share is above the threshold; `None` otherwise.

    `kind` reflects the failure mode. An uneven split drops the smaller variant
    harder (`ASYMMETRIC_EXCLUSION`). An even split still drops a non-random
    population, for example users whose distinct ID churns at login
    (`IDENTITY_CHURN`).
    """
    if multiple_variant_handling != MultipleVariantHandling.EXCLUDE:
        return None

    variants = flag_variants or []
    if not variants:
        return None

    total_observed = sum(total_exposures.values())
    if total_observed <= 0:
        return None

    multiple_observed = total_exposures.get(MULTIPLE_VARIANT_KEY, 0)
    multiple_variant_percentage = (multiple_observed / total_observed) * 100
    if multiple_variant_percentage <= MULTIPLE_VARIANT_BIAS_THRESHOLD:
        return None

    rollout_percentages = [variant.get("rollout_percentage", 0) for variant in variants]
    kind = (
        MultiVariantBiasKind.IDENTITY_CHURN
        if is_evenly_distributed(rollout_percentages)
        else MultiVariantBiasKind.ASYMMETRIC_EXCLUSION
    )

    return BiasRisk(multiple_variant_percentage=multiple_variant_percentage, kind=kind)
