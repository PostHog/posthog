"""
Release conditions that override the variant. Pure functions, no I/O.

The flag service evaluates release conditions in their stored order, and the first match wins. A condition
whose variant override names one of the flag's variants serves that variant to the users it matches,
instead of the variant from the hash. An override that names no variant is ignored.
See `get_match` in rust/feature-flags/src/flags/flag_matching.rs and `pinned_variant` in flag_operations.rs.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.flag_state import is_single_variant_shipped, shipped_variant_key
from products.experiments.backend.health.condition_changes import conditions_net_effect
from products.experiments.backend.health.context import (
    FlagHistory,
    FlagState,
    HealthContext,
    ReachableCondition,
    VariantProperty,
)
from products.experiments.backend.health.pinned_share import (
    PinnedConditions,
    PinnedShareGrade,
    grade_pinned_share,
    pinned_conditions,
    pinned_share_severity,
    pinned_variant_keys,
)
from products.experiments.backend.health.skips import CheckOutcome, CheckSkip, flag_to_check
from products.experiments.backend.health.split_changes import format_change_time
from products.feature_flags.backend.facade.edits import ConditionsChange

# pinned: the subcodes are sent as `finding_subcode` on the health finding events, so insights group on them.
# Every condition that includes users pins a variant, so no user is randomly assigned. One variant gets
# everyone, or each variant gets a different group of users, so the results compare nothing valid.
ALL_CONDITIONS_PINNED = "all_conditions_pinned"
# Some conditions pin a variant. The users they match count in that variant's results without random
# assignment, so they bias the comparison unless the analysis excludes them, for example as test users.
SOME_CONDITIONS_PINNED = "some_conditions_pinned"
# Every condition that includes users pins the variant that one property names, so the code that sets the
# property assigns the variants. The comparison is valid if that code assigns at random, which PostHog can't see.
ASSIGNED_BY_PROPERTY = "assigned_by_property"


@frozen
class _Pins:
    pinned: tuple[ReachableCondition, ...]
    all_pinned: bool
    # The pinned conditions whose variant the analysis includes, in evaluation order.
    analyzed: tuple[ReachableCondition, ...]
    graded: PinnedConditions


def overrides_to_grade(ctx: HealthContext) -> PinnedConditions | None:
    """The overrides in place that SOME_CONDITIONS_PINNED is graded by, or None when it is not graded."""
    flag = flag_to_check(ctx, before_launch=True)
    if isinstance(flag, CheckSkip) or not ctx.is_launched:
        return None
    pins = _pins(ctx, flag)
    if pins is None or pins.all_pinned:
        return None
    return pins.graded


def forced_variant_release_condition(ctx: HealthContext) -> CheckOutcome:
    flag = flag_to_check(ctx, before_launch=True)
    if isinstance(flag, CheckSkip):
        return flag
    pins = _pins(ctx, flag)
    if pins is None:
        return None
    is_draft = not ctx.is_launched

    if not pins.all_pinned:
        return _some_conditions_pinned(pins, ctx, is_draft)

    pinned_numbers = [condition.number for condition in pins.pinned]
    pinned_keys = pinned_variant_keys(pins.pinned)
    # The shipped finding already says that everyone gets this variant.
    if ctx.is_running and is_single_variant_shipped(flag) and pinned_keys == [shipped_variant_key(flag)]:
        return None
    set_after_launch = _set_after_launch(ctx, pinned_numbers)
    variant_property = _shared_variant_property(pins.pinned)
    if variant_property is not None and len(pinned_keys) > 1:
        return _finding(
            subcode=ASSIGNED_BY_PROPERTY,
            severity=ExperimentHealthFindingSeverity.INFO,
            title="Variants are assigned outside PostHog",
            detail=_assigned_by_property_detail(variant_property.key, set_after_launch.sentence),
            pinned_numbers=pinned_numbers,
            pinned_keys=pinned_keys,
            diagnostic_ref="A7b",
            grade_evidence={"variant_property": variant_property.key, **set_after_launch.evidence},
        )
    return _finding(
        subcode=ALL_CONDITIONS_PINNED,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title="No users are randomly assigned to a variant",
        detail=_all_pinned_detail(pinned_numbers, pinned_keys, is_draft, set_after_launch),
        pinned_numbers=pinned_numbers,
        pinned_keys=pinned_keys,
        diagnostic_ref="A7b",
        grade_evidence=set_after_launch.evidence,
    )


def _pins(ctx: HealthContext, flag: FlagState) -> _Pins | None:
    pinned = tuple(condition for condition in flag.reachable_conditions if condition.pinned_variant is not None)
    if not pinned:
        return None
    # A variant that the experiment excludes is not in the results, so its pins can't bias them.
    analyzed = tuple(condition for condition in pinned if condition.pinned_variant not in ctx.excluded_variant_keys)
    return _Pins(
        pinned=pinned,
        all_pinned=len(pinned) == len(flag.reachable_conditions),
        analyzed=analyzed,
        graded=pinned_conditions(analyzed, flag.variants),
    )


def _some_conditions_pinned(pins: _Pins, ctx: HealthContext, is_draft: bool) -> ExperimentHealthFinding | None:
    if not pins.analyzed:
        return None
    graded = pins.graded
    grade = None if is_draft or not graded.weighted else grade_pinned_share(graded, ctx.condition_set_traffic)
    severity = pinned_share_severity(grade)
    if severity is None:
        # A pin to a variant with 0% in the split is the only source of that variant's results, however few.
        if not graded.unweighted:
            return None
        severity = ExperimentHealthFindingSeverity.INFO
    pinned_numbers = [condition.number for condition in pins.analyzed]
    pinned_keys = pinned_variant_keys(pins.analyzed)
    set_after_launch = _set_after_launch(ctx, pinned_numbers)
    return _finding(
        subcode=SOME_CONDITIONS_PINNED,
        severity=severity,
        title="Some users are not randomly assigned to a variant",
        detail=_some_pinned_detail(
            pinned_numbers, pinned_keys, is_draft, grade, pinned_variant_keys(graded.unweighted), set_after_launch
        ),
        pinned_numbers=pinned_numbers,
        pinned_keys=pinned_keys,
        diagnostic_ref="A7",
        grade_evidence={**(grade.evidence() if grade is not None else {}), **set_after_launch.evidence},
        reason=grade.finding_reason if grade is not None else None,
    )


@frozen
class _SetAfterLaunch:
    # One sentence after a leading space, or empty when no override was set after launch.
    sentence: str
    evidence: dict[str, str | int | float | None]
    # Whether every override of these conditions was set after launch. Removing them then puts back the variants
    # that users got at launch, so moving the start date is enough.
    covers_all: bool

    def remedy_after_removal(self) -> str:
        if self.covers_all:
            return "Then move the experiment's start date to after the removal."
        return "Then reset the experiment, or move its start date to after the removal."


def _set_after_launch(ctx: HealthContext, numbers: Sequence[int]) -> _SetAfterLaunch:
    """The overrides of these conditions that were set after launch while people were already exposed. The
    release-condition check leaves them to this finding, so that one override gets one row."""
    history = ctx.flag_history
    effect = (
        conditions_net_effect(history.counted(ConditionsChange), current=history.release_conditions)
        if isinstance(history, FlagHistory)
        else None
    )
    added = [] if effect is None else [o for o in effect.overrides.added if o.condition_number in numbers]
    if history is None or not added:
        return _SetAfterLaunch(sentence="", evidence={}, covers_all=False)
    set_at = max(override.set_at for override in added)
    at = format_change_time(set_at, history.team_timezone)
    if len(added) == 1:
        sentence = (
            f" The override of Set {added[0].condition_number} was set on {at}, after launch, so users it matches "
            "who were exposed before may have switched variants."
        )
    else:
        names = _set_names(sorted(override.condition_number for override in added))
        sentence = (
            f" The overrides of {names} were set after launch, last on {at}, so users they match who were exposed "
            "before may have switched variants."
        )
    return _SetAfterLaunch(
        sentence=sentence,
        evidence={"override_set_at": set_at.astimezone(UTC).isoformat()},
        covers_all={override.condition_number for override in added} >= set(numbers),
    )


def _shared_variant_property(conditions: Sequence[ReachableCondition]) -> VariantProperty | None:
    properties = {condition.variant_property for condition in conditions}
    return next(iter(properties)) if len(properties) == 1 else None


def _quoted(keys: Sequence[str]) -> str:
    return ", ".join(f'"{key}"' for key in keys)


def _set_names(numbers: Sequence[int]) -> str:
    if len(numbers) == 1:
        return f"Set {numbers[0]}"
    return "Sets " + ", ".join(str(number) for number in numbers[:-1]) + f" and {numbers[-1]}"


def _all_pinned_detail(
    numbers: Sequence[int], pinned_keys: Sequence[str], is_draft: bool, set_after_launch: _SetAfterLaunch
) -> str:
    overrides = "the override" if len(numbers) == 1 else "the overrides"
    when = "after launch " if is_draft else ""
    if len(pinned_keys) == 1:
        key = pinned_keys[0]
        fact = (
            f'Every release condition that includes users sets the variant override "{key}", so {when}all users '
            f'in the experiment get "{key}".'
        )
        why = f'With no other variant to compare against, the results can\'t show whether "{key}" makes a difference.'
        fix = (
            f'If you meant to roll out "{key}", end the experiment with a conclusion. Otherwise remove {overrides} '
            f'so users are assigned at random. Users who already saw "{key}" can then switch to another variant. '
            f"{set_after_launch.remedy_after_removal()}"
        )
    else:
        fact = (
            f"Every release condition that includes users sets a variant override ({_quoted(pinned_keys)}), so "
            f"{when}each user gets the variant of the condition they match instead of a random one."
        )
        why = (
            "Each variant then holds a different group of users, so a difference in the results can come from "
            "who those users are and not from the variant."
        )
        fix = (
            f"Remove {overrides} so users are assigned at random. Users who already saw a variant can then "
            f"switch to another one. {set_after_launch.remedy_after_removal()}"
        )
    if is_draft:
        fix = f"Remove {overrides} before launch so users are assigned at random."
    return f"{fact}{set_after_launch.sentence} {why} {fix}"


def _assigned_by_property_detail(variant_property: str, set_after_launch: str) -> str:
    return (
        f'Each release condition that includes users matches the users whose property "{variant_property}" holds a '
        f'variant key, and serves them that variant. So the code that sets "{variant_property}" assigns the '
        f"variants, not PostHog.{set_after_launch} If it assigns at random, each variant gets similar users. If it "
        "assigns by who the users are, for example by plan or country, a difference in the results can come from "
        "those users and not from the variant."
    )


def _some_pinned_detail(
    numbers: Sequence[int],
    pinned_keys: Sequence[str],
    is_draft: bool,
    grade: PinnedShareGrade | None,
    unweighted_keys: Sequence[str],
    set_after_launch: _SetAfterLaunch,
) -> str:
    if len(numbers) == 1:
        key = pinned_keys[0]
        overrides, them = "the override", "it"
        fact = (
            f'{_set_names(numbers)} sets the variant override "{key}", so users who match it always get "{key}" '
            "instead of a random variant."
        )
    else:
        overrides, them = "the overrides", "them"
        fact = (
            f"{_set_names(numbers)} set variant overrides ({_quoted(pinned_keys)}), so users who match them "
            "always get the variant of their condition instead of a random one."
        )
    why = (
        f"{'After launch they count' if is_draft else 'They still count'} in the results, so if they behave "
        "differently from other users, the results of their variant shift for a reason other than the variant."
    )
    if is_draft:
        fix = (
            f"An override helps to test the experiment before launch. Remove {them} before launch, unless the "
            "filter for internal and test users excludes these users from the results."
        )
    else:
        fix = (
            "If these are internal or test users, check that the filter for internal and test users excludes "
            f"them from the results. Otherwise remove {overrides}. Users who match {them} can then switch variants. "
            f"{set_after_launch.remedy_after_removal()}"
        )
    if grade is not None:
        fact += grade.sentence(them)
    if len(unweighted_keys) == 1:
        fact += (
            f' Nobody gets "{unweighted_keys[0]}" at random, so the results of "{unweighted_keys[0]}" show only '
            "these users."
        )
    elif unweighted_keys:
        names = " or ".join(f'"{key}"' for key in unweighted_keys)
        fact += f" Nobody gets {names} at random, so their results show only these users."
    return f"{fact}{set_after_launch.sentence} {why} {fix}"


def _finding(
    *,
    subcode: str,
    severity: ExperimentHealthFindingSeverity,
    title: str,
    detail: str,
    pinned_numbers: Sequence[int],
    pinned_keys: Sequence[str],
    diagnostic_ref: str,
    grade_evidence: Mapping[str, str | int | float | None] | None = None,
    reason: str | None = None,
) -> ExperimentHealthFinding:
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.FORCED_VARIANT_RELEASE_CONDITION,
        subcode=subcode,
        reason=reason,
        severity=severity,
        title=title,
        detail=detail,
        evidence={
            "pinned_condition_sets": ", ".join(str(number) for number in pinned_numbers),
            "pinned_variant_keys": ", ".join(pinned_keys),
            **(grade_evidence or {}),
        },
        actions=(ExperimentHealthFindingActionKind.EDIT_RELEASE_CONDITIONS,),
        diagnostic_ref=diagnostic_ref,
    )
