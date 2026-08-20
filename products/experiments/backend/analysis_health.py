"""
Analysis-health signals for experiments. Pure functions — no I/O.

Evaluates two signals: asymmetric `$multiple`-exclusion bias, and sample ratio
mismatch that is strong enough to alert on. Designed to grow (low exposures,
variant drift, ...) as additional pure evaluators when needed.
"""

import math

from posthog.schema import BiasRisk, MultipleVariantHandling

MULTIPLE_VARIANT_KEY = "$multiple"

# `$multiple` share above this triggers the warning. Below this, the asymmetric-
# exclusion effect on arm means is too small to matter in practice.
MULTIPLE_VARIANT_BIAS_THRESHOLD = 0.1  # on the 0-100 scale (0.1 = 0.1%)

# Sample ratio mismatch alert gate. The passive banner draws at p < 0.001; the alert
# reuses that p-value but adds the experiments scout's volume guard so low-volume noise
# stays quiet: a minimum bucketed-exposure floor, plus a per-variant 3σ check on the
# observed share, since a small chi-squared p-value can still sit inside the noise band
# at low counts.
SRM_ALERT_P_VALUE_THRESHOLD = 0.001
SRM_ALERT_MIN_TOTAL_EXPOSURES = 1000
SRM_ALERT_SIGMA = 3.0


def evaluate_bias_risk(
    flag_variants: list[dict] | None,
    multiple_variant_handling: MultipleVariantHandling,
    total_exposures: dict[str, int],
) -> BiasRisk | None:
    """
    Empirically observed multi-variant exclusion bias risk: EXCLUDE handling +
    observed `$multiple` share above the threshold.
    Returns a `BiasRisk` only when both conditions hold; `None` otherwise.

    An even split does not clear the risk: EXCLUDE drops the non-random `$multiple`
    population from every arm, so a high `$multiple` share biases arm means whatever
    the configured split.
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

    return BiasRisk(multiple_variant_percentage=multiple_variant_percentage)


def srm_crosses_alert_threshold(
    observed: dict[str, int],
    expected: dict[str, float],
    p_value: float | None,
) -> bool:
    """Whether a computed sample ratio mismatch is strong enough to alert on.

    `observed` maps each variant to its exposure count; `expected` maps the same variants to
    the counts the configured split predicts (both come straight from the SRM computation, so
    `$multiple`, holdout, and excluded variants are already dropped). Returns True only when the
    chi-squared p-value clears the threshold at healthy volume and at least one variant's observed
    share sits more than 3σ from expected.
    """
    total = sum(observed.get(key, 0) for key in expected)
    if total < SRM_ALERT_MIN_TOTAL_EXPOSURES:
        return False

    if p_value is None or p_value >= SRM_ALERT_P_VALUE_THRESHOLD:
        return False

    for key, expected_count in expected.items():
        expected_share = expected_count / total
        if not 0 < expected_share < 1:
            continue
        sigma = math.sqrt(expected_share * (1 - expected_share) / total)
        observed_share = observed.get(key, 0) / total
        if abs(observed_share - expected_share) > SRM_ALERT_SIGMA * sigma:
            return True

    return False
