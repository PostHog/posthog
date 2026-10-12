"""
Release conditions that override the variant. Pure functions, no I/O.

The flag service evaluates release conditions in their stored order, and the first match wins. A condition
whose variant override names one of the flag's variants serves that variant to the users it matches,
instead of the variant from the hash. An override that names no variant is ignored.
See `get_match` in rust/feature-flags/src/flags/flag_matching.rs and `pinned_variant` in flag_operations.rs.
"""

from collections.abc import Sequence

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.flag_state import is_single_variant_shipped, shipped_variant_key
from products.experiments.backend.health.context import FlagReleaseGroup, FlagState, HealthContext

# pinned: the subcodes are sent as `finding_variant` on the health finding events, so insights group on them.
# Every condition that includes users pins a variant, so no user is randomly assigned. One variant gets
# everyone, or each variant gets a different group of users, so the results compare nothing valid.
ALL_CONDITIONS_PINNED = "all_conditions_pinned"
# Some conditions pin a variant. The users they match count in that variant's results without random
# assignment, so they bias the comparison unless the analysis excludes them, for example as test users.
SOME_CONDITIONS_PINNED = "some_conditions_pinned"


def forced_variant_release_condition(ctx: HealthContext) -> ExperimentHealthFinding | None:
    flag = ctx.flag
    # After the end the flag often holds the shipped decision, not the setup of the run.
    if flag is None or flag.deleted or ctx.has_ended or ctx.archived:
        return None

    variant_keys = {variant.key for variant in flag.variants if variant.key}
    live_sets = _live_condition_sets(flag)
    pinned_sets = [(number, group) for number, group in live_sets if group.variant in variant_keys]
    if not pinned_sets:
        return None
    pinned_keys = list(dict.fromkeys(group.variant for _, group in pinned_sets if group.variant))
    is_draft = not ctx.is_launched

    if len(pinned_sets) < len(live_sets):
        return _finding(
            subcode=SOME_CONDITIONS_PINNED,
            severity=ExperimentHealthFindingSeverity.INFO,
            title="Some users are not randomly assigned to a variant",
            detail=_some_pinned_detail([number for number, _ in pinned_sets], pinned_keys, is_draft),
            pinned_sets=pinned_sets,
            pinned_keys=pinned_keys,
            diagnostic_ref="A7",
        )

    # The shipped finding already says that everyone gets this variant.
    if ctx.is_running and is_single_variant_shipped(flag) and pinned_keys == [shipped_variant_key(flag)]:
        return None
    return _finding(
        subcode=ALL_CONDITIONS_PINNED,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title="No users are randomly assigned to a variant",
        detail=_all_pinned_detail([number for number, _ in pinned_sets], pinned_keys, is_draft),
        pinned_sets=pinned_sets,
        pinned_keys=pinned_keys,
        diagnostic_ref="A7b",
    )


def _live_condition_sets(flag: FlagState) -> list[tuple[int, FlagReleaseGroup]]:
    """The release conditions that can include users, numbered from 1 as the page labels them ("Set 2")."""
    # A request without a group's key skips that group's conditions, so a group condition ends the evaluation
    # only for the requests of its group type. A person condition ends it for every request.
    ended_group_types: set[int] = set()
    live: list[tuple[int, FlagReleaseGroup]] = []
    for number, group in enumerate(flag.release_groups, start=1):
        group_type = group.aggregation_group_type_index
        if group_type in ended_group_types:
            continue
        # A missing rollout serves every matched user, as on the flag service.
        rollout = 100 if group.rollout_percentage is None else group.rollout_percentage
        if rollout > 0:
            live.append((number, group))
        # A condition without properties matches every request that reaches it. At a full rollout, or with early
        # exit at any rollout including 0%, the evaluation ends there for all of them.
        if not group.property_count and (rollout >= 100 or flag.early_exit):
            if group_type is None:
                break
            ended_group_types.add(group_type)
    return live


def _quoted(keys: Sequence[str]) -> str:
    return ", ".join(f'"{key}"' for key in keys)


def _set_names(numbers: Sequence[int]) -> str:
    if len(numbers) == 1:
        return f"Set {numbers[0]}"
    return "Sets " + ", ".join(str(number) for number in numbers[:-1]) + f" and {numbers[-1]}"


def _all_pinned_detail(numbers: Sequence[int], pinned_keys: Sequence[str], is_draft: bool) -> str:
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
            f'so users are assigned at random. Users who already saw "{key}" can then switch to another variant.'
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
            "switch to another one."
        )
    if is_draft:
        fix = f"Remove {overrides} before launch so users are assigned at random."
    return f"{fact} {why} {fix}"


def _some_pinned_detail(numbers: Sequence[int], pinned_keys: Sequence[str], is_draft: bool) -> str:
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
            f"them from the results. Otherwise remove {overrides}."
        )
    return f"{fact} {why} {fix}"


def _finding(
    *,
    subcode: str,
    severity: ExperimentHealthFindingSeverity,
    title: str,
    detail: str,
    pinned_sets: Sequence[tuple[int, FlagReleaseGroup]],
    pinned_keys: Sequence[str],
    diagnostic_ref: str,
) -> ExperimentHealthFinding:
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.FORCED_VARIANT_RELEASE_CONDITION,
        subcode=subcode,
        severity=severity,
        title=title,
        detail=detail,
        evidence={
            "pinned_condition_sets": ", ".join(str(number) for number, _ in pinned_sets),
            "pinned_variant_keys": ", ".join(pinned_keys),
        },
        actions=(ExperimentHealthFindingActionKind.EDIT_RELEASE_CONDITIONS,),
        diagnostic_ref=diagnostic_ref,
    )
