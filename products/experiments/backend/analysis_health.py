"""
Analysis-health signals for experiments. Pure functions — no I/O.

Evaluates two signals: asymmetric `$multiple`-exclusion bias on uneven splits, and the
likeliest cause of a flagged sample ratio mismatch. Designed to grow (low exposures,
variant drift, ...) as additional pure evaluators when needed.
"""

from posthog.schema import BiasRisk, MultipleVariantHandling, SrmCause, SrmDiagnosis, SrmSurfaceSkew

from posthog.dataclasses import frozen

from products.experiments.backend.variant_distribution import is_evenly_distributed

MULTIPLE_VARIANT_KEY = "$multiple"

# `$multiple` share above this triggers the warning. Below this, the asymmetric-
# exclusion effect on arm means is too small to matter in practice.
MULTIPLE_VARIANT_BIAS_THRESHOLD = 0.1  # on the 0-100 scale (0.1 = 0.1%)

# The chi-squared test counts as a mismatch below this p-value.
SRM_SIGNIFICANCE_P_VALUE = 0.001

# Below this expected count per variant, a flagged mismatch is usually transient: over a
# short window, uneven arrival of traffic moves the observed split more than assignment does.
SRM_CONFIDENT_EXPECTED_COUNT = 1000

# A surface needs this many first exposures, and this share of all of them, before its
# variant split says anything about the experiment as a whole.
SURFACE_MIN_EXPOSURES = 100
SURFACE_MIN_SHARE = 0.05

# A surface reads as skewed when its busiest variant runs this far above the share the
# rollout expects, and as balanced when the busiest variant stays within this band of it in
# either direction. Under an uneven rollout the busiest variant can sit below its own share,
# which is still a skew, so the balanced test compares the absolute deviation.
SURFACE_SKEW_MARGIN = 0.25
SURFACE_BALANCED_MARGIN = 0.10


@frozen
class SurfaceExposureSplit:
    """First exposures recorded on one surface, and the variant that takes most of them."""

    surface: str
    exposures: int
    dominant_variant: str
    dominant_exposures: int

    @property
    def dominant_share(self) -> float:
        return self.dominant_exposures / self.exposures if self.exposures else 0.0


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


def evaluate_srm_diagnosis(
    p_value: float,
    expected_counts: dict[str, float],
    surface_splits: list[SurfaceExposureSplit] | None = None,
) -> SrmDiagnosis | None:
    """
    Name the likeliest cause of a flagged sample ratio mismatch.

    Returns `None` when the chi-squared test is not significant, so the result always
    describes a live mismatch. Callers may run this twice: once without `surface_splits`
    to get the answers that need no extra query, and again with them only if the first
    pass came back `UNKNOWN`.
    """
    if p_value >= SRM_SIGNIFICANCE_P_VALUE or not expected_counts:
        return None

    smallest_expected_count = min(expected_counts.values())
    if smallest_expected_count < SRM_CONFIDENT_EXPECTED_COUNT:
        return SrmDiagnosis(cause=SrmCause.LOW_SAMPLE_SIZE, smallest_expected_count=smallest_expected_count)

    surface_skew = _find_surface_skew(expected_counts, surface_splits or [])
    if surface_skew is not None:
        return SrmDiagnosis(cause=SrmCause.CAPTURE_BY_SURFACE, surface_skew=surface_skew)

    return SrmDiagnosis(cause=SrmCause.UNKNOWN)


def _find_surface_skew(
    expected_counts: dict[str, float],
    surface_splits: list[SurfaceExposureSplit],
) -> SrmSurfaceSkew | None:
    """
    Report the most skewed surface, but only alongside a surface that carries the
    configured split. The same skew on every surface means the imbalance is upstream of
    where exposures are recorded, not a surface the other variants cannot reach.
    """
    # The share denominator is the whole exposed population, not the surfaces this got
    # handed: the query returns only the busiest few, so summing them would overstate every
    # surface's share and let one through the floor that is smaller than it looks.
    total_expected = sum(expected_counts.values())
    if total_expected <= 0:
        return None

    expected_shares = {variant: count / total_expected for variant, count in expected_counts.items()}

    skew: SrmSurfaceSkew | None = None
    largest_excess = SURFACE_SKEW_MARGIN
    has_balanced_surface = False

    for split in surface_splits:
        if split.exposures < SURFACE_MIN_EXPOSURES or split.exposures / total_expected < SURFACE_MIN_SHARE:
            continue
        expected_share = expected_shares.get(split.dominant_variant)
        if expected_share is None:
            continue

        excess = split.dominant_share - expected_share
        if excess >= largest_excess:
            largest_excess = excess
            skew = SrmSurfaceSkew(
                surface=split.surface,
                variant=split.dominant_variant,
                variant_percentage=split.dominant_share * 100,
                expected_percentage=expected_share * 100,
                exposures=split.exposures,
            )
        elif abs(excess) <= SURFACE_BALANCED_MARGIN:
            has_balanced_surface = True

    return skew if has_balanced_surface else None
