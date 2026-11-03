"""
Changes of the flag's release conditions, read from the flag's activity log. Pure functions, no I/O.

The flags facade (`facade/edits.py`) owns which condition changes move people to another variant. A rollout change
alone moves people in or out too, but an increase is harmless, so it is not a change here.

Each change pairs the conditions before it with the conditions after it, as the flag page's history does, so an
override stays with its condition when the filters of that condition change.

An override set after launch that is still in place is the forced-variant check's to report, with the time it was
set. An override that is gone leaves no state to report, so the release-condition check reports it.
"""

import itertools
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from enum import StrEnum

from posthog.dataclasses import frozen

from products.experiments.backend.health.context import ChangeWindow
from products.experiments.backend.health.split_changes import EXPOSURE_FREEZE_JOB_TYPES
from products.feature_flags.backend.facade.edits import (
    ConditionsChange,
    ReleaseCondition,
    ReleaseConditions,
    moves_people,
    order_moves_people,
    pair_conditions,
    parse_release_conditions,
    parse_variants,
    split_variant_keys,
)


class ConditionsChangeShape(StrEnum):
    # pinned: the finding's subcodes. The page sends them as `finding_subcode` on the health finding events.
    VARIANT_OVERRIDE_CHANGED = "variant_override_changed"
    CONDITIONS_CHANGED = "conditions_changed"
    REVERTED = "reverted"


@frozen
class AddedOverride:
    variant: str
    # The number of its condition in the flag now, from 1, as the page and the flag service number them.
    condition_number: int
    set_at: datetime


@frozen
class RemovedOverride:
    variant: str
    # The number of its condition in the flag now. None when the condition is gone too.
    condition_number: int | None
    # Whether its condition matches now what it matched while the override was in place, at the same rollout, so
    # the users it serves now are the users the override served.
    same_audience: bool
    # None when the override was in place before the first change.
    set_at: datetime | None
    # The first change of the override when it was set back, otherwise the change that removed it.
    removed_at: datetime
    restored_at: datetime | None
    # From the first change of the override to the last, when its condition serves the same variant before and
    # after them: no override, or the same one set back. Only people exposed in this window can have switched
    # variants. None when an override was in place before the first change and is gone now.
    temporary_window: ChangeWindow | None


@frozen
class EditedOverride:
    variant: str
    condition_number: int


@frozen
class OverrideChanges:
    # Overrides set by the changes that are still in place. A changed override counts as set.
    added: tuple[AddedOverride, ...]
    # Overrides that the changes removed, set and removed again, or changed and set back.
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
    reordered: bool
    # The conditions that kept their override while their criteria changed. The people who match them differently
    # move between the override's variant and a random one.
    edited_overrides: tuple[EditedOverride, ...]


def conditions_change_from_activity(
    *,
    changed_at: datetime,
    job_type: object,
    before_groups: object,
    after_groups: object,
    before_aggregation: object,
    after_aggregation: object,
    before_variants: object,
    after_variants: object,
) -> ConditionsChange | None:
    """The release-condition change in one activity log row of the flag, or None when the row does not change who
    the conditions match or which variant they serve. The aggregations and variants are the flag-level ones of the
    row."""
    if job_type in EXPOSURE_FREEZE_JOB_TYPES:
        return None
    if before_groups == after_groups and before_aggregation == after_aggregation:
        return None
    before = parse_release_conditions(
        before_groups,
        flag_aggregation=before_aggregation,
        variant_keys=split_variant_keys(parse_variants(before_variants)),
    )
    after = parse_release_conditions(
        after_groups,
        flag_aggregation=after_aggregation,
        variant_keys=split_variant_keys(parse_variants(after_variants)),
    )
    if conditions_shape(before, after) is None:
        return None
    return ConditionsChange(changed_at=changed_at, before=before, after=after)


def conditions_shape(before: ReleaseConditions, after: ReleaseConditions) -> ConditionsChangeShape | None:
    """What changed between two sets of release conditions, or None when they match the same people and serve
    them the same variants. The first match wins."""
    return _shape(before, after, pair_conditions(before, after))


def conditions_net_effect(
    changes: Sequence[ConditionsChange], *, current: ReleaseConditions | None
) -> ConditionsNetEffect | None:
    """
    `current` are the flag's conditions now, which the condition numbers follow. A save that changes nothing this
    module reads, such as the order of conditions without an override, is no change, so it can come after the
    last change and renumber the conditions. None numbers them as after the last change.
    """
    if not changes:
        return None
    first = changes[0]
    last = changes[-1]
    followed = _rejoin(_follow(changes), first.before, last.after)
    now = last.after if current is None else current
    now_ids = (
        followed.end_ids
        if current is None
        else _carry_ids(last.after, followed.end_ids, current, itertools.count(_next_id(followed)))
    )
    numbers = {condition_id: number for number, condition_id in enumerate(now_ids, start=1)}
    audience_now = {condition_id: _audience(condition) for condition_id, condition in zip(now_ids, now)}
    overrides, touched = _override_changes(followed, first.before, last.after, numbers, audience_now)
    start_index = {condition_id: index for index, condition_id in enumerate(followed.start_ids)}
    net_pairs = {
        index: start_index[condition_id]
        for index, condition_id in enumerate(followed.end_ids)
        if condition_id in start_index
    }
    return ConditionsNetEffect(
        shape=_shape(first.before, last.after, net_pairs) or ConditionsChangeShape.REVERTED,
        from_conditions=first.before,
        to_conditions=last.after,
        first=first,
        last=last,
        change_count=len(changes),
        overrides=overrides,
        audience_changed=_criteria_without(first.before, followed.start_ids, touched)
        != _criteria_without(last.after, followed.end_ids, touched),
        reordered=order_moves_people(first.before, last.after, net_pairs),
        edited_overrides=tuple(
            EditedOverride(variant=variant, condition_number=numbers[condition_id])
            for end_index, start_index in sorted(net_pairs.items())
            for condition_id, old, new in [
                (followed.end_ids[end_index], first.before[start_index], last.after[end_index])
            ]
            for variant in [new.variant]
            if variant is not None
            and condition_id not in touched
            and condition_id in numbers
            and new.rollout > 0
            and new.criteria != old.criteria
        ),
    )


@frozen
class _VariantChange:
    condition_id: int
    changed_at: datetime
    before: str | None
    after: str | None
    before_audience: tuple[str, float] | None


@frozen
class _Followed:
    start_ids: tuple[int, ...]
    end_ids: tuple[int, ...]
    variant_changes: tuple[_VariantChange, ...]


def _follow(changes: Sequence[ConditionsChange]) -> _Followed:
    new_ids = itertools.count()
    start_ids = tuple(next(new_ids) for _ in changes[0].before)
    conditions, ids = changes[0].before, start_ids
    variant_changes = []
    for change in changes:
        # A save that changes only what this module ignores, such as a rollout, is not a change, and neither is an
        # exposure freeze. A change can then start from other conditions than the ones the change before it ended
        # with, so those are paired too.
        before_ids = _carry_ids(conditions, ids, change.before, new_ids)
        after_ids = _carry_ids(change.before, before_ids, change.after, new_ids)
        before = dict(zip(before_ids, change.before))
        after = dict(zip(after_ids, change.after))
        for condition_id in dict.fromkeys([*before_ids, *after_ids]):
            old, new = before.get(condition_id), after.get(condition_id)
            if moves_people(old, new):
                variant_changes.append(
                    _VariantChange(
                        condition_id=condition_id,
                        changed_at=change.changed_at,
                        before=_variant(old),
                        after=_variant(new),
                        before_audience=_audience(old) if old is not None else None,
                    )
                )
        conditions, ids = change.after, after_ids
    return _Followed(start_ids=start_ids, end_ids=ids, variant_changes=tuple(variant_changes))


def _rejoin(followed: _Followed, start: ReleaseConditions, end: ReleaseConditions) -> _Followed:
    """A condition that one change removes and a later change adds back is two conditions to the pairing of each
    change. Pairing the conditions gone by the end with the ones new since the start joins them again."""
    start_ids, end_ids = set(followed.start_ids), set(followed.end_ids)
    gone = [index for index, condition_id in enumerate(followed.start_ids) if condition_id not in end_ids]
    new = [index for index, condition_id in enumerate(followed.end_ids) if condition_id not in start_ids]
    pairs = pair_conditions(tuple(start[index] for index in gone), tuple(end[index] for index in new))
    joined = {
        followed.end_ids[new[new_index]]: followed.start_ids[gone[gone_index]]
        for new_index, gone_index in pairs.items()
    }
    return _Followed(
        start_ids=followed.start_ids,
        end_ids=tuple(joined.get(condition_id, condition_id) for condition_id in followed.end_ids),
        variant_changes=tuple(
            replace(change, condition_id=joined.get(change.condition_id, change.condition_id))
            for change in followed.variant_changes
        ),
    )


def _next_id(followed: _Followed) -> int:
    ids = [*followed.start_ids, *followed.end_ids, *(change.condition_id for change in followed.variant_changes)]
    return max(ids, default=-1) + 1


def _carry_ids(
    before: ReleaseConditions, ids: tuple[int, ...], after: ReleaseConditions, new_ids: Iterator[int]
) -> tuple[int, ...]:
    pairs = pair_conditions(before, after)
    return tuple(ids[pairs[index]] if index in pairs else next(new_ids) for index in range(len(after)))


def _override_changes(
    followed: _Followed,
    start: ReleaseConditions,
    end: ReleaseConditions,
    numbers: Mapping[int, int],
    audience_now: Mapping[int, tuple[str, float]],
) -> tuple[OverrideChanges, set[int]]:
    """The override changes, and the ids of the conditions they touch."""
    start_variants = {condition_id: condition.variant for condition_id, condition in zip(followed.start_ids, start)}
    end_variants = {condition_id: condition.variant for condition_id, condition in zip(followed.end_ids, end)}
    added: list[AddedOverride] = []
    removed: list[RemovedOverride] = []
    by_condition: dict[int, list[_VariantChange]] = {}
    for change in followed.variant_changes:
        by_condition.setdefault(change.condition_id, []).append(change)
    for condition_id, changes in by_condition.items():
        start_variant = start_variants.get(condition_id)
        end_variant = end_variants.get(condition_id)
        number = numbers.get(condition_id)
        if end_variant is not None and end_variant != start_variant:
            set_at = _last_set(changes, end_variant)
            if set_at is not None and number is not None:
                added.append(AddedOverride(variant=end_variant, condition_number=number, set_at=set_at))
        elif end_variant is not None:
            removed.append(
                RemovedOverride(
                    variant=end_variant,
                    condition_number=number,
                    same_audience=changes[0].before_audience == audience_now.get(condition_id),
                    set_at=None,
                    removed_at=changes[0].changed_at,
                    restored_at=changes[-1].changed_at,
                    temporary_window=ChangeWindow(start=changes[0].changed_at, end=changes[-1].changed_at),
                )
            )
        else:
            removal_index = next(
                (index for index in range(len(changes) - 1, -1, -1) if changes[index].after is None), None
            )
            if removal_index is None:
                continue
            removal = changes[removal_index]
            if removal.before is None:
                continue
            removed.append(
                RemovedOverride(
                    variant=removal.before,
                    condition_number=number,
                    same_audience=removal.before_audience == audience_now.get(condition_id),
                    set_at=None
                    if removal.before == start_variant
                    else _last_set(changes[:removal_index], removal.before),
                    removed_at=removal.changed_at,
                    restored_at=None,
                    temporary_window=None
                    if start_variant is not None
                    else ChangeWindow(start=changes[0].changed_at, end=removal.changed_at),
                )
            )
    touched = set(by_condition)
    return OverrideChanges(added=tuple(added), removed=tuple(removed)), touched


def _last_set(changes: Sequence[_VariantChange], variant: str) -> datetime | None:
    return next((change.changed_at for change in reversed(changes) if change.after == variant), None)


def _shape(
    before: ReleaseConditions, after: ReleaseConditions, pairs: Mapping[int, int]
) -> ConditionsChangeShape | None:
    paired = set(pairs.values())
    sides = [
        *((before[before_index], after[after_index]) for after_index, before_index in pairs.items()),
        *((condition, None) for index, condition in enumerate(before) if index not in paired),
        *((None, condition) for index, condition in enumerate(after) if index not in pairs),
    ]
    if any(moves_people(old, new) for old, new in sides) or order_moves_people(before, after, pairs):
        return ConditionsChangeShape.VARIANT_OVERRIDE_CHANGED
    # When no variant moves, the order does not decide who is in the flag.
    if sorted(condition.criteria for condition in before) != sorted(condition.criteria for condition in after):
        return ConditionsChangeShape.CONDITIONS_CHANGED
    return None


def _criteria_without(conditions: ReleaseConditions, ids: tuple[int, ...], touched: set[int]) -> list[str]:
    return sorted(condition.criteria for condition, condition_id in zip(conditions, ids) if condition_id not in touched)


def _variant(condition: ReleaseCondition | None) -> str | None:
    return condition.variant if condition is not None else None


def _audience(condition: ReleaseCondition) -> tuple[str, float]:
    return condition.criteria, condition.rollout
