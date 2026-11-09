"""Multi-variant exclusion bias on an uneven split. Pure functions, no I/O."""

from collections.abc import Collection, Mapping, Sequence

from posthog.schema import BiasRisk, MultipleVariantHandling

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.skips import (
    NO_FLAG,
    NOT_AFTER_END,
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    not_applicable,
)
from products.feature_flags.backend.facade.edits import FlagVariant

MULTIPLE_VARIANT_KEY = "$multiple"

# `$multiple` share above this triggers the warning. Below this, the asymmetric-
# exclusion effect on arm means is too small to matter in practice.
MULTIPLE_VARIANT_BIAS_THRESHOLD = 0.1  # on the 0-100 scale (0.1 = 0.1%)
# One or two testers who switch between variants must not trigger the warning.
MULTIPLE_VARIANT_BIAS_MINIMUM_COUNT = 5


def evaluate_bias_risk(
    variants: Sequence[FlagVariant],
    excluded_variant_keys: Collection[str],
    multiple_variant_handling: MultipleVariantHandling,
    total_exposures: Mapping[str, int],
) -> BiasRisk | None:
    """
    Empirically observed multi-variant exclusion bias risk: uneven shares of the variants that the flag serves and the
    analysis compares + EXCLUDE handling + observed `$multiple` share above the threshold, from enough users.
    Returns a `BiasRisk` only when all three conditions hold; `None` otherwise.
    """
    if multiple_variant_handling != MultipleVariantHandling.EXCLUDE:
        return None

    # Excluded variants don't count, because the exposure query drops their events before it counts users in several
    # variants. `is_evenly_distributed` needs shares that add up to 100. Shares one point apart are even, like 34/33/33.
    compared = [
        variant.rollout_percentage
        for variant in variants
        if variant.rollout_percentage is not None
        and variant.rollout_percentage > 0
        and variant.key not in excluded_variant_keys
    ]
    if len(compared) < 2 or max(compared) - min(compared) <= 1:
        return None

    multiple_observed = total_exposures.get(MULTIPLE_VARIANT_KEY, 0)
    if multiple_observed < MULTIPLE_VARIANT_BIAS_MINIMUM_COUNT:
        return None

    multiple_variant_percentage = (multiple_observed / sum(total_exposures.values())) * 100
    if multiple_variant_percentage <= MULTIPLE_VARIANT_BIAS_THRESHOLD:
        return None

    return BiasRisk(multiple_variant_percentage=multiple_variant_percentage)


def bias_risk_multiple_excluded(ctx: HealthContext) -> CheckOutcome:
    if ctx.exposures is None:
        return not_applicable(RUNS_AFTER_LAUNCH)
    if ctx.flag is None:
        return not_applicable(NO_FLAG)
    if ctx.has_ended:
        return not_applicable(NOT_AFTER_END)
    risk = evaluate_bias_risk(
        variants=ctx.flag.variants,
        excluded_variant_keys=ctx.excluded_variant_keys,
        multiple_variant_handling=ctx.exposures.multiple_variant_handling,
        total_exposures=ctx.exposures.total_exposures,
    )
    if risk is None:
        return None
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.BIAS_RISK_MULTIPLE_EXCLUDED,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title="The uneven split may bias the results",
        detail=(
            f"{risk.multiple_variant_percentage:.1f}% of users were exposed to multiple variants. "
            "With an uneven variant split and the Exclude handling, these users were dropped more often "
            "from the smaller variant, so its metrics can be biased. Use an even split and control "
            "exposure with the overall rollout, or switch the handling to First seen."
        ),
        evidence={"multiple_variant_percentage": risk.multiple_variant_percentage},
        actions=(
            ExperimentHealthFindingActionKind.ADJUST_DISTRIBUTION,
            ExperimentHealthFindingActionKind.USE_FIRST_SEEN_VARIANT,
        ),
        diagnostic_ref="A1",
    )
