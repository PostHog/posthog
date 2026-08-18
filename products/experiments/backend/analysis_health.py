"""
Analysis-health signals for experiments. Pure functions — no I/O.

Evaluates two signals: asymmetric `$multiple`-exclusion bias on uneven splits, and the
botlike exposure composition (missing user agent or `$device_type`) behind a skewed split.
Designed to grow (low exposures, variant drift, ...) as additional pure evaluators when needed.
"""

from posthog.schema import BiasRisk, ExposureCompositionWarning, MultipleVariantHandling

from products.experiments.backend.variant_distribution import is_evenly_distributed

MULTIPLE_VARIANT_KEY = "$multiple"

# `$multiple` share above this triggers the warning. Below this, the asymmetric-
# exclusion effect on arm means is too small to matter in practice.
MULTIPLE_VARIANT_BIAS_THRESHOLD = 0.1  # on the 0-100 scale (0.1 = 0.1%)

# Missing-user-agent or missing-`$device_type` share above this is large enough to explain a
# skewed split. Below it, the botlike population is too small to move the arms.
EXPOSURE_COMPOSITION_THRESHOLD = 5.0  # on the 0-100 scale (5.0 = 5%)


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


def evaluate_exposure_composition(
    total_exposed: int,
    missing_user_agent: int,
    missing_device_type: int,
) -> ExposureCompositionWarning | None:
    """
    Botlike exposure composition behind a skewed split: the share of exposed entities whose
    first exposure carried no user agent or no `$device_type`. Returns a warning only when one
    of those shares is above the threshold; `None` otherwise.

    The caller decides whether the split is actually off (sample-ratio mismatch) before asking,
    so this stays a pure share check with no split math of its own.
    """
    if total_exposed <= 0:
        return None

    missing_user_agent_percentage = (missing_user_agent / total_exposed) * 100
    missing_device_type_percentage = (missing_device_type / total_exposed) * 100

    if (
        missing_user_agent_percentage <= EXPOSURE_COMPOSITION_THRESHOLD
        and missing_device_type_percentage <= EXPOSURE_COMPOSITION_THRESHOLD
    ):
        return None

    return ExposureCompositionWarning(
        missing_user_agent_percentage=missing_user_agent_percentage,
        missing_device_type_percentage=missing_device_type_percentage,
    )
