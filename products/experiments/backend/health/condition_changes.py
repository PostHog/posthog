"""
Changes of the flag's release conditions, read from the flag's activity log. Pure functions, no I/O.

A condition whose criteria change, or a condition that is added or removed, moves people into or out of the flag,
never to another variant (`get_match` in rust/feature-flags/src/flags/flag_matching.rs). A variant override does
move people: everyone a condition with an override matches gets that variant instead of the one from the hash.
A rollout change alone moves people in or out too, but an increase is harmless, so it is not a change here.

An override set after launch that is still in place is the forced-variant check's to report, with the time it was
set. An override that is gone leaves no state to report, so the release-condition check reports it.
"""

import json
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from posthog.dataclasses import frozen

from products.experiments.backend.health.context import ConditionsChange, ReleaseCondition
from products.experiments.backend.health.split_changes import EXPOSURE_FREEZE_JOB_TYPES

ReleaseConditions = tuple[ReleaseCondition, ...]


class ConditionsChangeShape(StrEnum):
    # pinned: the finding's subcodes. The page sends them as `finding_variant` on the health finding events.
    VARIANT_OVERRIDE_CHANGED = "variant_override_changed"
    CONDITIONS_CHANGED = "conditions_changed"
    REVERTED = "reverted"


@frozen
class AddedOverride:
    criteria: str
    variant: str
    # The number of its condition after the last change, from 1, as the page and the flag service number them.
    condition_number: int
    set_at: datetime


@frozen
class RemovedOverride:
    criteria: str
    variant: str
    # The number of its condition after the last change. None when the condition is gone too.
    condition_number: int | None
    # None when the override was in place before the first change.
    set_at: datetime | None
    removed_at: datetime


@frozen
class OverrideChanges:
    # Overrides set by the changes that are still in place. A changed override counts as set.
    added: tuple[AddedOverride, ...]
    # Overrides that the changes removed, or set and removed again, whose condition has no override now.
    removed: tuple[RemovedOverride, ...]


@frozen
class ConditionsNetEffect:
    shape: ConditionsChangeShape
    from_conditions: ReleaseConditions
    to_conditions: ReleaseConditions
    first: ConditionsChange
    last: ConditionsChange
    change_count: int
    overrides: OverrideChanges
    # Whether the conditions that no override change touches match other people after the last change.
    audience_changed: bool


def conditions_change_from_activity(
    *, changed_at: datetime, job_type: object, before_groups: object, after_groups: object
) -> ConditionsChange | None:
    """The release-condition change in one activity log row of the flag, or None when the row does not change who
    the conditions match or which variant they override."""
    if job_type in EXPOSURE_FREEZE_JOB_TYPES:
        return None
    before = parse_release_conditions(before_groups)
    after = parse_release_conditions(after_groups)
    if conditions_shape(before, after) is None:
        return None
    return ConditionsChange(changed_at=changed_at, before=before, after=after)


def parse_release_conditions(groups: object) -> ReleaseConditions:
    return tuple(_condition(group) for group in groups) if isinstance(groups, list) else ()


def conditions_shape(before: ReleaseConditions, after: ReleaseConditions) -> ConditionsChangeShape | None:
    """What changed between two sets of release conditions, or None when they match the same people with the same
    overrides. The first match wins."""
    if _overrides(before) != _overrides(after):
        return ConditionsChangeShape.VARIANT_OVERRIDE_CHANGED
    # Without overrides, the order does not decide who is in the flag.
    if sorted(condition.criteria for condition in before) != sorted(condition.criteria for condition in after):
        return ConditionsChangeShape.CONDITIONS_CHANGED
    return None


def conditions_net_effect(changes: Sequence[ConditionsChange]) -> ConditionsNetEffect | None:
    if not changes:
        return None
    first = changes[0]
    last = changes[-1]
    overrides = override_changes(changes)
    touched = {override.criteria for override in overrides.added} | {
        override.criteria for override in overrides.removed
    }
    return ConditionsNetEffect(
        shape=conditions_shape(first.before, last.after) or ConditionsChangeShape.REVERTED,
        from_conditions=first.before,
        to_conditions=last.after,
        first=first,
        last=last,
        change_count=len(changes),
        overrides=overrides,
        audience_changed=_criteria_without(first.before, touched) != _criteria_without(last.after, touched),
    )


def override_changes(changes: Sequence[ConditionsChange]) -> OverrideChanges:
    if not changes:
        return OverrideChanges(added=(), removed=())
    final = changes[-1].after
    final_overrides = set(_overrides(final))
    final_overridden = {override.criteria for override in final_overrides}
    set_at: dict[_Override, datetime | None] = dict.fromkeys(_overrides(changes[0].before))
    removed_at: dict[_Override, datetime] = {}
    for change in changes:
        before = set(_overrides(change.before))
        after = set(_overrides(change.after))
        for override in after - before:
            set_at.setdefault(override, change.changed_at)
        for override in before - after:
            removed_at[override] = change.changed_at
    numbers = {
        _Override(criteria=condition.criteria, variant=condition.variant): number
        for number, condition in enumerate(final, start=1)
        if condition.variant
    }
    criteria_numbers = {condition.criteria: number for number, condition in reversed(list(enumerate(final, start=1)))}
    return OverrideChanges(
        added=tuple(
            AddedOverride(
                criteria=override.criteria,
                variant=override.variant,
                condition_number=numbers[override],
                set_at=at,
            )
            for override, at in set_at.items()
            if at is not None and override in final_overrides
        ),
        removed=tuple(
            RemovedOverride(
                criteria=override.criteria,
                variant=override.variant,
                condition_number=criteria_numbers.get(override.criteria),
                set_at=set_at.get(override),
                removed_at=at,
            )
            for override, at in removed_at.items()
            # A condition whose override changed to another variant is still overridden, so it is an added override.
            if override not in final_overrides and override.criteria not in final_overridden
        ),
    )


def _criteria_without(conditions: ReleaseConditions, criteria: set[str]) -> list[str]:
    return sorted(condition.criteria for condition in conditions if condition.criteria not in criteria)


@frozen
class _Override:
    criteria: str
    variant: str


def _overrides(conditions: ReleaseConditions) -> list[_Override]:
    # The order of the overrides matters, because a person who matches two conditions gets the first one's variant.
    return [
        _Override(criteria=condition.criteria, variant=condition.variant)
        for condition in conditions
        if condition.variant
    ]


def _condition(group: object) -> ReleaseCondition:
    if not isinstance(group, dict):
        return ReleaseCondition(criteria=json.dumps(group, sort_keys=True, default=str), variant=None)
    properties = group.get("properties")
    variant = group.get("variant")
    return ReleaseCondition(
        criteria=json.dumps(
            [
                group.get("aggregation_group_type_index"),
                # The filters of a condition all have to match, so their order does not matter.
                sorted(_property_signature(prop) for prop in properties) if isinstance(properties, list) else None,
            ],
            sort_keys=True,
            default=str,
        ),
        variant=variant if isinstance(variant, str) and variant else None,
    )


def _property_signature(prop: object) -> str:
    # The fields that decide a match, as the flag page's history compares them (releaseConditionsDiff.ts).
    if not isinstance(prop, dict):
        return json.dumps(prop, sort_keys=True, default=str)
    return json.dumps(
        [prop.get(field) for field in ("type", "key", "operator", "value", "group_type_index")],
        sort_keys=True,
        default=str,
    )
