from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.split_changed import split_changed_mid_run
from products.experiments.backend.health.context import ExposureTotals, HealthContext
from products.experiments.backend.health.skips import RUNS_AFTER_LAUNCH, CheckOutcome, not_applicable

SAMPLE_RATIO_MISMATCH_P_VALUE = 0.001

# pinned: the subcode is sent as `finding_variant` on the health finding events, so insights group on it.
SPLIT_CHANGED = "split_changed"


def reads_flag_history(exposures: ExposureTotals) -> bool:
    """Whether `srm` reads the flag history on these totals. The exposure query loads the history only then, because
    the load reads the flag's activity log and can query the exposures."""
    p_value = exposures.sample_ratio_mismatch_p_value
    return p_value is not None and p_value < SAMPLE_RATIO_MISMATCH_P_VALUE


def srm(ctx: HealthContext) -> CheckOutcome:
    if ctx.exposures is None:
        return not_applicable(RUNS_AFTER_LAUNCH)
    p_value = ctx.exposures.sample_ratio_mismatch_p_value
    if p_value is None:
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
    if p_value >= SAMPLE_RATIO_MISMATCH_P_VALUE:
        return None
    # The test compares everyone exposed since launch with the current split. After a split change that moved exposed
    # people, a mismatch is expected, and the split change warning carries the next step. That warning also counts a
    # change whose exposure answer is unknown. Its next step then moves the start date past the change, and the test
    # of the new window reports a mismatch with another cause as a warning again.
    split_change = split_changed_mid_run(ctx)
    if (
        isinstance(split_change, ExperimentHealthFinding)
        and split_change.severity == ExperimentHealthFindingSeverity.WARNING
    ):
        return ExperimentHealthFinding(
            code=ExperimentHealthFindingCode.SRM,
            subcode=SPLIT_CHANGED,
            severity=ExperimentHealthFindingSeverity.INFO,
            title="Users are not split as configured because the split changed",
            detail=(
                "The distribution of users across variants doesn't match your current rollout percentages "
                f"(p < {SAMPLE_RATIO_MISMATCH_P_VALUE}). The variant split changed after launch while people were "
                "exposed, so some of them got their variants from another split. This check compares everyone with "
                f'the current split, so the mismatch is expected. Follow the steps in "{split_change.title}" to fix '
                "the results."
            ),
            evidence={"p_value": p_value},
            actions=(),
            diagnostic_ref="A2",
        )
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
