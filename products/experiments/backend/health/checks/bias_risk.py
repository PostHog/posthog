"""Multi-variant exclusion bias on an uneven split. Pure functions, no I/O."""

from collections.abc import Collection, Mapping, Sequence

from posthog.schema import BiasRisk, MultipleVariantHandling

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthValueKey,
)
from products.experiments.backend.health.checks.forced_variant import assigns_nobody_by_split
from products.experiments.backend.health.context import ExposureTotals, HealthContext
from products.experiments.backend.health.skips import (
    NEEDS_EXPOSURES,
    NEEDS_SPLIT_VARIANTS,
    NO_FLAG,
    NOT_AFTER_END,
    RUNS_AFTER_LAUNCH,
    SPLIT_ASSIGNS_NOBODY,
    CheckOutcome,
    CheckSkip,
    CheckValues,
    not_applicable,
)
from products.feature_flags.backend.facade.edits import FlagVariant

MULTIPLE_VARIANT_KEY = "$multiple"

# `$multiple` share above this triggers the warning. Below this, the asymmetric-
# exclusion effect on arm means is too small to matter in practice.
MULTIPLE_VARIANT_BIAS_THRESHOLD = 0.1  # on the 0-100 scale (0.1 = 0.1%)
# One or two testers who switch between variants must not trigger the warning.
MULTIPLE_VARIANT_BIAS_MINIMUM_COUNT = 5


def _multiple_variant_share(
    variants: Sequence[FlagVariant],
    excluded_variant_keys: Collection[str],
    multiple_variant_handling: MultipleVariantHandling,
    total_exposures: Mapping[str, int],
) -> float | CheckSkip:
    """The share of exposed users seen in multiple variants, on the 0-100 scale, or why the risk can't arise."""
    if multiple_variant_handling != MultipleVariantHandling.EXCLUDE:
        return not_applicable('Runs when "Multiple variant handling" is "Exclude from analysis"')
    # Excluded variants don't count, because the exposure query drops their events before it counts users in several
    # variants. `is_evenly_distributed` needs shares that add up to 100. Shares one point apart are even, like 34/33/33.
    compared = [
        variant.rollout_percentage
        for variant in variants
        if variant.rollout_percentage is not None
        and variant.rollout_percentage > 0
        and variant.key not in excluded_variant_keys
    ]
    if len(compared) < 2:
        return not_applicable(NEEDS_SPLIT_VARIANTS)
    if max(compared) - min(compared) <= 1:
        return not_applicable("Runs when the variant split is uneven")
    total_observed = sum(total_exposures.values())
    if total_observed <= 0:
        return not_applicable(NEEDS_EXPOSURES)
    return total_exposures.get(MULTIPLE_VARIANT_KEY, 0) / total_observed * 100


def _too_few_to_warn(total_exposures: Mapping[str, int]) -> bool:
    return total_exposures.get(MULTIPLE_VARIANT_KEY, 0) < MULTIPLE_VARIANT_BIAS_MINIMUM_COUNT


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
    share = _multiple_variant_share(variants, excluded_variant_keys, multiple_variant_handling, total_exposures)
    if isinstance(share, CheckSkip) or share <= MULTIPLE_VARIANT_BIAS_THRESHOLD or _too_few_to_warn(total_exposures):
        return None
    return BiasRisk(multiple_variant_percentage=share)


def multiple_variant_count(exposures: ExposureTotals) -> int | None:
    """The users exposed to more than one variant, or None under "First seen". There the exposure query gives each user
    their first variant, so it counts none of these users."""
    if exposures.multiple_variant_handling != MultipleVariantHandling.EXCLUDE:
        return None
    return exposures.total_exposures.get(MULTIPLE_VARIANT_KEY, 0)


def multiple_variant_values(exposures: ExposureTotals) -> CheckValues:
    """The users exposed to more than one variant, which the bias and the multiple variants checks read."""
    values: dict[ExperimentHealthValueKey, int | float | str | None] = {
        ExperimentHealthValueKey.EXPOSED_COUNT: exposures.total,
        ExperimentHealthValueKey.MULTIPLE_VARIANT_HANDLING: exposures.multiple_variant_handling.value,
    }
    multiple = multiple_variant_count(exposures)
    if multiple is not None:
        values[ExperimentHealthValueKey.MULTIPLE_VARIANT_COUNT] = multiple
        values[ExperimentHealthValueKey.MULTIPLE_VARIANT_PERCENTAGE] = (
            multiple / exposures.total * 100 if exposures.total else None
        )
    return values


def bias_risk_values(ctx: HealthContext) -> CheckValues:
    return multiple_variant_values(ctx.exposures) if ctx.exposures else {}


def bias_risk_multiple_excluded(ctx: HealthContext) -> CheckOutcome:
    if ctx.exposures is None:
        return not_applicable(RUNS_AFTER_LAUNCH)
    if ctx.flag is None:
        return not_applicable(NO_FLAG)
    if ctx.has_ended:
        return not_applicable(NOT_AFTER_END)
    # The split's shares then say nothing about the variants' sizes. `forced_variant_release_condition` explains it.
    if assigns_nobody_by_split(ctx.flag):
        return not_applicable(SPLIT_ASSIGNS_NOBODY)
    share = _multiple_variant_share(
        variants=ctx.flag.variants,
        excluded_variant_keys=ctx.excluded_variant_keys,
        multiple_variant_handling=ctx.exposures.multiple_variant_handling,
        total_exposures=ctx.exposures.total_exposures,
    )
    if isinstance(share, CheckSkip):
        return share
    if share <= MULTIPLE_VARIANT_BIAS_THRESHOLD or _too_few_to_warn(ctx.exposures.total_exposures):
        return None
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.BIAS_RISK_MULTIPLE_EXCLUDED,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title="The uneven split may bias the results",
        detail=(
            f"{share:.1f}% of users were exposed to multiple variants. "
            "With an uneven variant split and the Exclude handling, these users were dropped more often "
            "from the smaller variant, so its metrics can be biased. Use an even split and control "
            "exposure with the overall rollout, or switch the handling to First seen."
        ),
        evidence={"multiple_variant_percentage": share},
        actions=(
            ExperimentHealthFindingActionKind.ADJUST_DISTRIBUTION,
            ExperimentHealthFindingActionKind.USE_FIRST_SEEN_VARIANT,
        ),
        diagnostic_ref="A1",
    )
