"""
Conflicting states of an experiment and its feature flag. Pure functions, no I/O.

A port of the page's `browserExperimentWarning` selector (frontend/src/scenes/experiments/experimentLogic.tsx)
and the flag helpers it calls (`hasZeroRollout`, `hasMultipleVariantsActive`, `isSingleVariantShipped`).
Change both sides together until the page reads these findings.

A running experiment whose flag has a 0% rollout is the exception. The flag service and local evaluation serve no
variant then, so people who still get one get it from the customer's own assignment, which only the flag's calls
show. Only the server reports that case.
"""

from datetime import UTC, datetime, timedelta

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.context import (
    ConditionSetTraffic,
    FlagHistoryNotChecked,
    FlagState,
    HealthContext,
    SplitChange,
)
from products.experiments.backend.health.split_changes import (
    SplitChangeShape,
    describe_split,
    format_change_time,
    net_effect,
)

# pinned: the page's warning keys. The page sends them as `finding_variant` and
# `warning_key` on its events, and picks the banner text by them.
RUNNING_BUT_FLAG_DISABLED = "running_but_flag_disabled"
RUNNING_BUT_NO_ROLLOUT = "running_but_no_rollout"
RUNNING_BUT_SINGLE_VARIANT_SHIPPED = "running_but_single_variant_shipped"
ENDED_BUT_MULTIPLE_VARIANTS_ROLLED_OUT = "ended_but_multiple_variants_rolled_out"
NOT_STARTED_BUT_MULTIPLE_VARIANTS_ROLLED_OUT = "not_started_but_multiple_variants_rolled_out"
# pinned: the page sends these as `finding_variant` on its events, as the keys above. No banner uses them.
RUNNING_BUT_FLAG_DELETED = "running_but_flag_deleted"
ASSIGNED_OUTSIDE_FLAG_SERVICE = "assigned_outside_flag_service"

# A bootstrap can come from a server's cached evaluation, and an older client can report a variant it cached before
# the rollout went to 0%. Calls in this time after the start of the window don't count as assigned outside the flag
# service, so that these leftovers don't hide a rollout that really stopped new exposures.
OUTSIDE_ASSIGNMENT_GRACE = timedelta(hours=1)
# A few people can get a variant from a developer's local override, or from a client that cached it before the
# rollout went to 0%.
_MIN_PEOPLE_ASSIGNED_OUTSIDE = 10
# A shorter window can still fill up, so an answer under the minimum is asked again sooner.
_OUTSIDE_ASSIGNMENT_SETTLED_AFTER = timedelta(days=1)

_NOT_RUNNING_BUT_EXPOSED_TITLE = "The experiment is not running, but users are exposed to multiple variants"


def flag_state(ctx: HealthContext) -> ExperimentHealthFinding | None:
    flag = ctx.flag
    if flag is None:
        return None

    if flag.deleted:
        # A deleted flag distributes no traffic, so the other flag-state findings don't apply. This branch
        # comes before the paused one because a flag is often disabled before it is deleted. The page's own
        # rule returns nothing here, so this finding has no banner, and the page's events that compare the
        # two report it as a difference.
        if ctx.is_running:
            return _finding(
                code=ExperimentHealthFindingCode.FLAG_OFF_WHILE_RUNNING,
                subcode=RUNNING_BUT_FLAG_DELETED,
                title="The experiment is running, but its feature flag is deleted",
                detail=(
                    "The linked feature flag is deleted, so no new users are being exposed. Users exposed "
                    "earlier are still included in the results. Open the feature flag and restore it, or end "
                    "the experiment with a conclusion."
                ),
            )
        return None

    zero_rollout = _has_zero_rollout(flag)
    single_variant_shipped = is_single_variant_shipped(flag)

    if ctx.is_running:
        if ctx.is_paused:
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
            traffic = ctx.condition_set_traffic
            if traffic is not None and traffic.people_assigned_outside >= _MIN_PEOPLE_ASSIGNED_OUTSIDE:
                return _assigned_outside(traffic)
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
            variant_key = shipped_variant_key(flag)
            shipped = f'Variant "{variant_key}" is' if variant_key else "One variant is"
            return _finding(
                code=ExperimentHealthFindingCode.VARIANT_SHIPPED_WHILE_RUNNING,
                subcode=RUNNING_BUT_SINGLE_VARIANT_SHIPPED,
                title="The experiment is running, but all users see a single variant",
                detail=(
                    f"{shipped} rolled out to 100% of users. {_rollout_since(ctx)}"
                    "The experiment is not comparing variants. "
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


def needs_outside_assignment_check(ctx: HealthContext) -> bool:
    """Whether this check reads the flag's calls: a running experiment whose flag has a 0% rollout."""
    flag = ctx.flag
    return ctx.is_running and not ctx.is_paused and flag is not None and not flag.deleted and _has_zero_rollout(flag)


def outside_assignment_unsettled(ctx: HealthContext, traffic: ConditionSetTraffic, *, now: datetime) -> bool:
    """Whether `traffic` holds too few people assigned outside the flag service only because its window is young."""
    return (
        needs_outside_assignment_check(ctx)
        and traffic.people_assigned_outside < _MIN_PEOPLE_ASSIGNED_OUTSIDE
        and now - traffic.since < _OUTSIDE_ASSIGNMENT_SETTLED_AFTER
    )


def _assigned_outside(traffic: ConditionSetTraffic) -> ExperimentHealthFinding:
    since = traffic.since + OUTSIDE_ASSIGNMENT_GRACE
    people = traffic.people_assigned_outside
    return _finding(
        code=ExperimentHealthFindingCode.FLAG_OFF_WHILE_RUNNING,
        subcode=ASSIGNED_OUTSIDE_FLAG_SERVICE,
        severity=ExperimentHealthFindingSeverity.INFO,
        title="Variants are assigned outside PostHog",
        detail=(
            "The linked feature flag has a 0% rollout, so PostHog assigns no variants. But "
            f"{people:,} {'user' if people == 1 else 'users'} got a variant since "
            f"{format_change_time(since, traffic.team_timezone)} from flag calls that PostHog didn't evaluate, so "
            "your own code assigns the variants, directly or through a bootstrap. These users count in the results. "
            "The flag's release conditions and variant split don't decide who gets which variant. If PostHog should "
            "assign the variants, increase the rollout and stop assigning them in your code."
        ),
        evidence={"people_assigned_outside": people, "assigned_outside_since": since.astimezone(UTC).isoformat()},
    )


def _finding(
    *,
    code: ExperimentHealthFindingCode,
    subcode: str,
    title: str,
    detail: str,
    evidence: dict[str, str | int | float | None] | None = None,
    severity: ExperimentHealthFindingSeverity = ExperimentHealthFindingSeverity.WARNING,
) -> ExperimentHealthFinding:
    return ExperimentHealthFinding(
        code=code,
        subcode=subcode,
        severity=severity,
        title=title,
        detail=detail,
        evidence=evidence or {},
        actions=(ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG,),
        diagnostic_ref="A5",
    )


def _rollout_since(ctx: HealthContext) -> str:
    # The split check leaves this rollout to this finding, so the finding carries the date of the change.
    history = ctx.flag_history
    if history is None:
        return ""
    effect = net_effect(
        history.of_kind(SplitChange) if isinstance(history, FlagHistoryNotChecked) else history.counted(SplitChange)
    )
    if effect is None or effect.shape != SplitChangeShape.VARIANT_ROLLED_OUT:
        return ""
    at = format_change_time(effect.last.changed_at, history.team_timezone)
    return f"It has been at 100% since {at}, and the split was {describe_split(effect.last.before)} before. "


def _has_zero_rollout(flag: FlagState) -> bool:
    # Only true when every release group is set to 0 explicitly. A group without a rollout
    # percentage serves everyone.
    return bool(flag.release_groups) and all(group.rollout_percentage == 0 for group in flag.release_groups)


def _has_multiple_variants_active(flag: FlagState) -> bool:
    # A variant without a rollout percentage counts as active, as on the flag itself.
    return sum(1 for variant in flag.variants if variant.rollout_percentage != 0) > 1


def is_single_variant_shipped(flag: FlagState) -> bool:
    first_group = flag.release_groups[0] if flag.release_groups else None
    return (
        flag.active
        and first_group is not None
        and first_group.property_count == 0
        and first_group.rollout_percentage == 100
        and any(variant.rollout_percentage == 100 for variant in flag.variants)
    )


def shipped_variant_key(flag: FlagState) -> str | None:
    return next((variant.key for variant in flag.variants if variant.rollout_percentage == 100), None) or None
