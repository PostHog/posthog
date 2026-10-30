"""
The flag's variants against the variants the analysis needs. Pure functions, no I/O.

The analysis reads its variants from the flag and compares each one with the baseline. Save and launch check
both, but the flag can change after that, and experiments saved before those checks never had them.
"""

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.skips import (
    NEEDS_VARIANTS,
    CheckOutcome,
    CheckSkip,
    flag_to_check,
    not_applicable,
)

# pinned: the subcodes are sent as `finding_subcode` on the health finding events, so insights group on them.
FLAG_HAS_NO_VARIANTS = "flag_has_no_variants"
NO_CONTROL_VARIANT = "no_control_variant"


def flag_variants_mismatch(ctx: HealthContext) -> CheckOutcome:
    # A deleted flag has a finding of its own, and the flag has to be restored first. After the end the flag
    # can change for good reasons, for example to a boolean flag that keeps the shipped variant.
    flag = flag_to_check(ctx, before_launch=True)
    if isinstance(flag, CheckSkip):
        return flag

    variant_keys = {variant.key for variant in flag.variants if variant.key}
    if not variant_keys:
        # A draft without variants is not set up yet. A running experiment had at least two at launch.
        if not ctx.is_running:
            return not_applicable(NEEDS_VARIANTS)
        return _finding(
            subcode=FLAG_HAS_NO_VARIANTS,
            title="The experiment is running, but its feature flag has no variants",
            detail=(
                "The linked feature flag has no variants, so the experiment can't count exposures or calculate "
                "results. Open the feature flag and add the experiment's variants back."
            ),
            evidence={},
        )

    if ctx.baseline_variant_key is not None and ctx.baseline_variant_key not in variant_keys:
        return _finding(
            subcode=NO_CONTROL_VARIANT,
            title="The baseline variant is not a variant of the feature flag",
            detail=(
                f'The baseline variant "{ctx.baseline_variant_key}" is not one of the linked feature flag\'s '
                "variants, so the results can't be calculated. Add the variant to the feature flag, or pick "
                "another baseline variant on the Settings tab."
            ),
            evidence={"baseline_variant_key": ctx.baseline_variant_key},
        )

    return None


def _finding(
    *, subcode: str, title: str, detail: str, evidence: dict[str, str | int | float | None]
) -> ExperimentHealthFinding:
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.FLAG_VARIANTS_MISMATCH,
        subcode=subcode,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=title,
        detail=detail,
        evidence=evidence,
        actions=(ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG,),
        diagnostic_ref="E4",
    )
