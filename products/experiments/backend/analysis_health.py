"""
Analysis-health signals for experiments. Pure functions — no I/O.

Evaluates two signals today: asymmetric `$multiple`-exclusion bias on uneven splits,
and a test-account filter that hides every exposure. Designed to grow (SRM, variant
drift, ...) as additional pure evaluators when needed.
"""

from posthog.schema import BiasRisk, MultipleVariantHandling

from products.experiments.backend.variant_distribution import is_evenly_distributed

MULTIPLE_VARIANT_KEY = "$multiple"

# `$multiple` share above this triggers the warning. Below this, the asymmetric-
# exclusion effect on arm means is too small to matter in practice.
MULTIPLE_VARIANT_BIAS_THRESHOLD = 0.1  # on the 0-100 scale (0.1 = 0.1%)


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


def is_test_account_filter_hiding_exposures(
    total_exposures: dict[str, int],
    filter_test_accounts: bool,
    team_has_test_account_filters: bool,
) -> bool:
    """
    Zero exposures while the test-account filter is on and the project has test-account
    filters configured. In that state the filter is the most likely reason exposures are
    missing: a person testing their own flag often matches the project's internal-user
    filters — typically their email domain — so their exposures drop out while the flag
    still evaluates and still fires events. Returns True only when all three hold.
    """
    if not filter_test_accounts or not team_has_test_account_filters:
        return False
    return sum(total_exposures.values()) == 0
