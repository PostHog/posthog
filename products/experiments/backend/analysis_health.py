"""
Analysis-health signals for experiments. Pure functions — no I/O.

Currently evaluates two signals: asymmetric `$multiple`-exclusion bias on uneven
splits, and dynamic cohorts referenced in exposure criteria. Designed to grow
(SRM, low exposures, variant drift, ...) as additional pure evaluators when needed.
"""

from typing import Any

from posthog.schema import BiasRisk, DynamicCohortExposureRisk, DynamicCohortReference, MultipleVariantHandling

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


def evaluate_dynamic_cohort_risk(referenced_cohorts: list[dict[str, Any]]) -> DynamicCohortExposureRisk | None:
    """
    Dynamic cohorts referenced in exposure criteria: flag evaluation checks the cohort's
    filters against live person properties, while the exposure query reads the cohort's
    stored membership list, which only recalculates periodically. Users who qualify in
    the gap between recalculations are routed into a variant by the flag before the
    exposure query reflects them, so exposure counts drift — eventually surfacing as a
    sample ratio mismatch. This is structural, not empirical: any dynamic cohort in
    exposure criteria carries the gap, so there is no observed-imbalance threshold.

    `referenced_cohorts` carries pre-fetched `{id, name, is_static}` for every cohort the
    experiment's exposure criteria references. Returns a risk naming the dynamic cohorts,
    or `None` when only static cohorts (or none) are referenced — static membership is
    fixed at creation, so flag evaluation and the exposure query agree.
    """
    dynamic = [cohort for cohort in referenced_cohorts if not cohort.get("is_static")]
    if not dynamic:
        return None

    return DynamicCohortExposureRisk(
        cohorts=[
            DynamicCohortReference(id=cohort["id"], name=cohort.get("name") or "")
            for cohort in sorted(dynamic, key=lambda cohort: cohort["id"])
        ]
    )
