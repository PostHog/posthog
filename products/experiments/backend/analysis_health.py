"""
Analysis-health signals for experiments. Pure functions — no I/O.

Evaluates two signals: asymmetric `$multiple`-exclusion bias on uneven splits, and
exposure coverage lost to failed flag evaluations. Designed to grow (SRM, variant
drift, ...) as additional pure evaluators when needed.
"""

from posthog.schema import BiasRisk, ExposureCoverage, MultipleVariantHandling

from products.experiments.backend.variant_distribution import is_evenly_distributed

MULTIPLE_VARIANT_KEY = "$multiple"

# `$multiple` share above this triggers the warning. Below this, the asymmetric-
# exclusion effect on arm means is too small to matter in practice.
MULTIPLE_VARIANT_BIAS_THRESHOLD = 0.1  # on the 0-100 scale (0.1 = 0.1%)

# Below this many flag callers the errored share is too noisy to act on.
EXPOSURE_COVERAGE_MINIMUM_CALLERS = 100

# Errored share above this triggers the warning, on the 0-100 scale. A few failed
# evaluations are normal on flaky networks; a persistent share means an unbootstrapped
# SDK is reading flags before they load.
EXPOSURE_COVERAGE_ERROR_THRESHOLD = 1.0


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


def evaluate_exposure_coverage(
    evaluated_entities: int,
    errored_entities_by_reason: dict[str, int],
) -> ExposureCoverage | None:
    """
    Exposure lost to flag evaluations that returned an error instead of a variant.
    Returns an `ExposureCoverage` only when enough entities called the flag and the
    errored share is above the threshold; `None` otherwise.

    This is a floor, not the full gap: an SDK that reads a flag before flags load
    sends no `$feature_flag_called` event at all, so those entities are in neither
    count.
    """
    errored_entities = sum(count for count in errored_entities_by_reason.values() if count > 0)
    total_callers = evaluated_entities + errored_entities
    if total_callers < EXPOSURE_COVERAGE_MINIMUM_CALLERS:
        return None

    errored_percentage = (errored_entities / total_callers) * 100
    if errored_percentage <= EXPOSURE_COVERAGE_ERROR_THRESHOLD:
        return None

    return ExposureCoverage(
        evaluated_entities=evaluated_entities,
        errored_entities=errored_entities,
        errored_percentage=errored_percentage,
        error_reasons=dict(
            sorted(
                ((reason, count) for reason, count in errored_entities_by_reason.items() if count > 0),
                key=lambda item: item[1],
                reverse=True,
            )
        ),
    )
