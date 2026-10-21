from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.context import HealthContext
from products.experiments.backend.health.skips import RUNS_AFTER_LAUNCH, CheckSkip, not_applicable

SAMPLE_RATIO_MISMATCH_P_VALUE = 0.001


def srm_skip(ctx: HealthContext) -> CheckSkip | None:
    if ctx.exposures is None:
        return not_applicable(RUNS_AFTER_LAUNCH)
    if ctx.exposures.sample_ratio_mismatch_p_value is None:
        # The exposure query compares only the variants with a share of the split that the analysis keeps, so after
        # a variant ships there is nothing to compare however many users are exposed.
        variants_in_split = [
            variant
            for variant in (ctx.flag.variants if ctx.flag else ())
            if variant.key and (variant.rollout_percentage or 0) > 0 and variant.key not in ctx.excluded_variant_keys
        ]
        if len(variants_in_split) < 2:
            return not_applicable("Needs two or more variants in the split")
        return not_applicable("Runs once enough users are exposed")
    return None


def srm(ctx: HealthContext) -> ExperimentHealthFinding | None:
    p_value = ctx.exposures.sample_ratio_mismatch_p_value if ctx.exposures else None
    if p_value is None or p_value >= SAMPLE_RATIO_MISMATCH_P_VALUE:
        return None
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.SRM,
        subcode=None,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title="Users are not split across variants as configured",
        detail=(
            "The distribution of users across variants doesn't match your configured rollout percentages "
            f"(p < {SAMPLE_RATIO_MISMATCH_P_VALUE}). This may indicate issues with randomization or data collection."
        ),
        evidence={"p_value": p_value},
        actions=(),
        diagnostic_ref="A2",
    )
