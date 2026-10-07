"""Multi-variant exclusion bias on an uneven split. Pure functions, no I/O."""

from collections.abc import Mapping, Sequence

from posthog.schema import BiasRisk, MultipleVariantHandling

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.variant_distribution import is_evenly_distributed

MULTIPLE_VARIANT_KEY = "$multiple"

# `$multiple` share above this triggers the warning. Below this, the asymmetric-
# exclusion effect on arm means is too small to matter in practice.
MULTIPLE_VARIANT_BIAS_THRESHOLD = 0.1  # on the 0-100 scale (0.1 = 0.1%)


def evaluate_bias_risk(
    rollout_percentages: Sequence[float | None],
    multiple_variant_handling: MultipleVariantHandling,
    total_exposures: Mapping[str, int],
) -> BiasRisk | None:
    """
    Empirically observed multi-variant exclusion bias risk: uneven split + EXCLUDE
    handling + observed `$multiple` share above the threshold.
    Returns a `BiasRisk` only when all three conditions hold; `None` otherwise.
    """
    if multiple_variant_handling != MultipleVariantHandling.EXCLUDE:
        return None

    if not rollout_percentages:
        return None

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


def bias_risk_multiple_excluded(ctx: HealthContext) -> ExperimentHealthFinding | None:
    if ctx.exposures is None or ctx.flag is None or ctx.has_ended:
        return None
    risk = evaluate_bias_risk(
        rollout_percentages=[variant.rollout_percentage for variant in ctx.flag.variants],
        multiple_variant_handling=ctx.exposures.multiple_variant_handling,
        total_exposures=ctx.exposures.total_exposures,
    )
    if risk is None:
        return None
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.BIAS_RISK_MULTIPLE_EXCLUDED,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title="Setup likely introduced bias",
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
