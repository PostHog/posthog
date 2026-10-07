"""
Conflicting states of an experiment and its feature flag. Pure functions, no I/O.

A port of the page's `experimentWarning` selector (frontend/src/scenes/experiments/experimentLogic.tsx)
and the flag helpers it calls (`hasZeroRollout`, `hasMultipleVariantsActive`, `isSingleVariantShipped`).
Change both sides together until the page reads these findings.
"""

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.context import FlagState, HealthContext

# pinned: the page's warning keys. The page sends them as `finding_variant` and
# `warning_key` on its events, and picks the banner text by them.
RUNNING_BUT_FLAG_DISABLED = "running_but_flag_disabled"
RUNNING_BUT_NO_ROLLOUT = "running_but_no_rollout"
RUNNING_BUT_SINGLE_VARIANT_SHIPPED = "running_but_single_variant_shipped"
ENDED_BUT_MULTIPLE_VARIANTS_ROLLED_OUT = "ended_but_multiple_variants_rolled_out"
NOT_STARTED_BUT_MULTIPLE_VARIANTS_ROLLED_OUT = "not_started_but_multiple_variants_rolled_out"

_NOT_RUNNING_BUT_EXPOSED_TITLE = "The experiment is not running, but users are exposed to multiple variants"


def flag_state(ctx: HealthContext) -> ExperimentHealthFinding | None:
    flag = ctx.flag
    # A deleted flag distributes no traffic, so flag-state findings don't apply.
    if flag is None or flag.deleted:
        return None

    zero_rollout = _has_zero_rollout(flag)
    single_variant_shipped = _is_single_variant_shipped(flag)

    if ctx.is_running:
        if not flag.active:
            return _finding(
                code=ExperimentHealthFindingCode.FLAG_OFF_WHILE_RUNNING,
                subcode=RUNNING_BUT_FLAG_DISABLED,
                title="The experiment is paused",
                detail=(
                    "The linked feature flag is disabled while the experiment has not been ended. "
                    "Resume or end the experiment."
                ),
            )
        if zero_rollout:
            return _finding(
                code=ExperimentHealthFindingCode.FLAG_OFF_WHILE_RUNNING,
                subcode=RUNNING_BUT_NO_ROLLOUT,
                title="The experiment is running, but no new users are being exposed",
                detail=(
                    "The linked feature flag has a 0% rollout, so no new users are being exposed. "
                    "Users exposed earlier are still included in the results. End the experiment with a "
                    "conclusion, or increase the rollout percentage to expose users."
                ),
            )
        if single_variant_shipped:
            variant_key = _shipped_variant_key(flag)
            shipped = f'Variant "{variant_key}" is' if variant_key else "One variant is"
            return _finding(
                code=ExperimentHealthFindingCode.VARIANT_SHIPPED_WHILE_RUNNING,
                subcode=RUNNING_BUT_SINGLE_VARIANT_SHIPPED,
                title="The experiment is running, but all users see a single variant",
                detail=(
                    f"{shipped} rolled out to 100% of users. The experiment is not comparing variants. "
                    "End the experiment with a conclusion, or adjust the variant distribution of the linked "
                    "feature flag to resume proper A/B testing."
                ),
                evidence={"variant_key": variant_key},
            )
    elif ctx.has_ended:
        if flag.active and _has_multiple_variants_active(flag) and not zero_rollout and not single_variant_shipped:
            return _finding(
                code=ExperimentHealthFindingCode.FLAG_LIVE_AFTER_END,
                subcode=ENDED_BUT_MULTIPLE_VARIANTS_ROLLED_OUT,
                title=_NOT_RUNNING_BUT_EXPOSED_TITLE,
                detail=(
                    "This experiment has ended, but the linked feature flag is still active and distributing "
                    "traffic across multiple variants. Disable the flag, or resume the experiment."
                ),
            )
    elif not ctx.archived:
        # The draft state is also reached again when resetting experiment measurements.
        if flag.active and _has_multiple_variants_active(flag) and not zero_rollout:
            return _finding(
                code=ExperimentHealthFindingCode.FLAG_LIVE_BEFORE_LAUNCH,
                subcode=NOT_STARTED_BUT_MULTIPLE_VARIANTS_ROLLED_OUT,
                title=_NOT_RUNNING_BUT_EXPOSED_TITLE,
                detail=(
                    "This experiment hasn't launched yet, but the linked feature flag is already active and "
                    "exposing users to multiple variants. Disable the flag, or start the experiment."
                ),
            )

    return None


def _finding(
    *,
    code: ExperimentHealthFindingCode,
    subcode: str,
    title: str,
    detail: str,
    evidence: dict[str, str | int | float | None] | None = None,
) -> ExperimentHealthFinding:
    return ExperimentHealthFinding(
        code=code,
        subcode=subcode,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=title,
        detail=detail,
        evidence=evidence or {},
        actions=(ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG,),
        diagnostic_ref="A5",
    )


def _has_zero_rollout(flag: FlagState) -> bool:
    # Only true when every release group is set to 0 explicitly. A group without a rollout
    # percentage serves everyone.
    return bool(flag.release_groups) and all(group.rollout_percentage == 0 for group in flag.release_groups)


def _has_multiple_variants_active(flag: FlagState) -> bool:
    # A variant without a rollout percentage counts as active, as on the flag itself.
    return sum(1 for variant in flag.variants if variant.rollout_percentage != 0) > 1


def _is_single_variant_shipped(flag: FlagState) -> bool:
    first_group = flag.release_groups[0] if flag.release_groups else None
    return (
        flag.active
        and first_group is not None
        and first_group.property_count == 0
        and first_group.rollout_percentage == 100
        and any(variant.rollout_percentage == 100 for variant in flag.variants)
    )


def _shipped_variant_key(flag: FlagState) -> str | None:
    return next((variant.key for variant in flag.variants if variant.rollout_percentage == 100), None) or None
