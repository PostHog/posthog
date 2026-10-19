"""
Changes of the flag's release conditions, read from the flag's activity log. Pure functions, no I/O.

A condition whose criteria change, or a condition that is added or removed, moves people into or out of the flag,
never to another variant (`get_match` in rust/feature-flags/src/flags/flag_matching.rs). A variant override does
move people: everyone a condition with an override matches gets that variant instead of the one from the hash.
The flag service evaluates the conditions in order, so the order moves people who match two conditions that serve
different variants. A rollout change alone moves people in or out too, but an increase is harmless, so it is not a
change here.

Each change pairs the conditions before it with the conditions after it, as the flag page's history does, so an
override stays with its condition when the filters of that condition change.

An override set after launch that is still in place is the forced-variant check's to report, with the time it was
set. An override that is gone leaves no state to report, so the release-condition check reports it.
"""

import json
import itertools
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from enum import StrEnum

from posthog.dataclasses import frozen

from products.experiments.backend.health.context import ConditionsChange, ReleaseCondition
from products.experiments.backend.health.split_changes import EXPOSURE_FREEZE_JOB_TYPES
from products.feature_flags.backend.facade.filters import condition_aggregation

ReleaseConditions = tuple[ReleaseCondition, ...]
_FOLLOWS_FLAG_AGGREGATION = "flag"


class ConditionsChangeShape(StrEnum):
    # pinned: the finding's subcodes. The page sends them as `finding_variant` on the health finding events.
    VARIANT_OVERRIDE_CHANGED = "variant_override_changed"
    CONDITIONS_CHANGED = "conditions_changed"
    REVERTED = "reverted"


@frozen
class AddedOverride:
    variant: str
    # The number of its condition after the last change, from 1, as the page and the flag service number them.
    condition_number: int
    set_at: datetime


@frozen
class RemovedOverride:
    variant: str
    # The number of its condition after the last change. None when the condition is gone too.
    condition_number: int | None
    # None when the override was in place before the first change.
    set_at: datetime | None
    # The first change of the override when it was set back, otherwise the change that removed it.
    removed_at: datetime
    restored_at: datetime | None


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
    # The numbers of the conditions after the last change that kept their override while their criteria changed.
    # The people who match them differently move between the override's variant and a random one.
    edited_override_numbers: tuple[int, ...]


def conditions_change_from_activity(
    *,
    changed_at: datetime,
    job_type: object,
    before_groups: object,
    after_groups: object,
    before_aggregation: object,
    after_aggregation: object,
) -> ConditionsChange | None:
    """The release-condition change in one activity log row of the flag, or None when the row does not change who
    the conditions match or which variant they serve. The aggregations are the flag-level ones of the row."""
    if job_type in EXPOSURE_FREEZE_JOB_TYPES:
        return None
    before = parse_release_conditions(before_groups, flag_aggregation=before_aggregation)
    after = parse_release_conditions(after_groups, flag_aggregation=after_aggregation)
    if conditions_shape(before, after) is None:
        return None
    return ConditionsChange(changed_at=changed_at, before=before, after=after)


def parse_release_conditions(groups: object, *, flag_aggregation: object = None) -> ReleaseConditions:
    aggregation = _group_type_index(flag_aggregation)
    return tuple(_condition(group, aggregation) for group in groups) if isinstance(groups, list) else ()


def conditions_shape(before: ReleaseConditions, after: ReleaseConditions) -> ConditionsChangeShape | None:
    """What changed between two sets of release conditions, or None when they match the same people and serve
    them the same variants. The first match wins."""
    return _shape(before, after, _pair_conditions(before, after))


def _pair_conditions(before: ReleaseConditions, after: ReleaseConditions) -> dict[int, int]:
    """
    The condition that each condition after a change was before it, as indexes from `after` to `before`. A
    condition without a pair was added or removed. The pairing is the one of the flag page's history
    (`diffReleaseConditionSets` in releaseConditionsDiff.ts): an unchanged condition first, then one with the same
    criteria, then a look-alike at the same position, then the only look-alike left.
    """
    pairs: dict[int, int] = {}

    def unpaired_before(index: int) -> bool:
        return index not in pairs.values()

    def pair_first(same: Callable[[ReleaseCondition, ReleaseCondition], bool]) -> None:
        for after_index, condition in enumerate(after):
            if after_index in pairs:
                continue
            before_index = next(
                (index for index, old in enumerate(before) if unpaired_before(index) and same(old, condition)), None
            )
            if before_index is not None:
                pairs[after_index] = before_index

    pair_first(lambda old, new: old == new)
    pair_first(lambda old, new: old.criteria == new.criteria)
    for after_index, condition in enumerate(after):
        if (
            after_index not in pairs
            and after_index < len(before)
            and unpaired_before(after_index)
            and _looks_alike(before[after_index], condition)
        ):
            pairs[after_index] = after_index
    # A condition that was edited and moved in one save has no partner at its position. It pairs with the one
    # condition left that it looks like. With several, no pair is safe, so they count as removed and added.
    for after_index, condition in enumerate(after):
        if after_index in pairs:
            continue
        candidates = [
            index for index, old in enumerate(before) if unpaired_before(index) and _looks_alike(old, condition)
        ]
        if len(candidates) == 1:
            pairs[after_index] = candidates[0]
    return pairs


def conditions_net_effect(changes: Sequence[ConditionsChange]) -> ConditionsNetEffect | None:
    if not changes:
        return None
    first = changes[0]
    last = changes[-1]
    followed = _rejoin(_follow(changes), first.before, last.after)
    overrides, touched = _override_changes(followed, first.before, last.after)
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
        reordered=_reordered(first.before, last.after, net_pairs),
        edited_override_numbers=tuple(
            end_index + 1
            for end_index, start_index in sorted(net_pairs.items())
            if followed.end_ids[end_index] not in touched
            and last.after[end_index].variant is not None
            and last.after[end_index].rollout > 0
            and last.after[end_index].criteria != first.before[start_index].criteria
        ),
    )


@frozen
class _VariantChange:
    condition_id: int
    changed_at: datetime
    before: str | None
    after: str | None


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
            if _moves_people(old, new):
                variant_changes.append(
                    _VariantChange(
                        condition_id=condition_id,
                        changed_at=change.changed_at,
                        before=_variant(old),
                        after=_variant(new),
                    )
                )
        conditions, ids = change.after, after_ids
    return _Followed(start_ids=start_ids, end_ids=ids, variant_changes=tuple(variant_changes))


def _rejoin(followed: _Followed, start: ReleaseConditions, end: ReleaseConditions) -> _Followed:
    """A condition that one change removes and a later change adds back is two conditions to the pairing of each
    change. Pairing the conditions gone by the end with the ones new since the start joins them again."""
    gone = [index for index, condition_id in enumerate(followed.start_ids) if condition_id not in followed.end_ids]
    new = [index for index, condition_id in enumerate(followed.end_ids) if condition_id not in followed.start_ids]
    pairs = _pair_conditions(tuple(start[index] for index in gone), tuple(end[index] for index in new))
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


def _carry_ids(
    before: ReleaseConditions, ids: tuple[int, ...], after: ReleaseConditions, new_ids: Iterator[int]
) -> tuple[int, ...]:
    pairs = _pair_conditions(before, after)
    return tuple(ids[pairs[index]] if index in pairs else next(new_ids) for index in range(len(after)))


def _override_changes(
    followed: _Followed, start: ReleaseConditions, end: ReleaseConditions
) -> tuple[OverrideChanges, set[int]]:
    """The override changes, and the ids of the conditions they touch."""
    start_variants = {condition_id: condition.variant for condition_id, condition in zip(followed.start_ids, start)}
    end_variants = {condition_id: condition.variant for condition_id, condition in zip(followed.end_ids, end)}
    end_numbers = {condition_id: number for number, condition_id in enumerate(followed.end_ids, start=1)}
    added: list[AddedOverride] = []
    removed: list[RemovedOverride] = []
    for condition_id in dict.fromkeys(change.condition_id for change in followed.variant_changes):
        changes = [change for change in followed.variant_changes if change.condition_id == condition_id]
        start_variant = start_variants.get(condition_id)
        end_variant = end_variants.get(condition_id)
        if end_variant is not None and end_variant != start_variant:
            set_at = _last_set(changes, end_variant)
            if set_at is not None:
                added.append(
                    AddedOverride(variant=end_variant, condition_number=end_numbers[condition_id], set_at=set_at)
                )
        elif end_variant is not None:
            removed.append(
                RemovedOverride(
                    variant=end_variant,
                    condition_number=end_numbers[condition_id],
                    set_at=None,
                    removed_at=changes[0].changed_at,
                    restored_at=changes[-1].changed_at,
                )
            )
        else:
            removal = next((change for change in reversed(changes) if change.after is None), None)
            if removal is None or removal.before is None:
                continue
            removed.append(
                RemovedOverride(
                    variant=removal.before,
                    condition_number=end_numbers.get(condition_id),
                    set_at=_last_set(changes[: changes.index(removal)], removal.before),
                    removed_at=removal.changed_at,
                    restored_at=None,
                )
            )
    touched = {change.condition_id for change in followed.variant_changes}
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
    if any(_moves_people(old, new) for old, new in sides) or _reordered(before, after, pairs):
        return ConditionsChangeShape.VARIANT_OVERRIDE_CHANGED
    # When no variant moves, the order does not decide who is in the flag.
    if sorted(condition.criteria for condition in before) != sorted(condition.criteria for condition in after):
        return ConditionsChangeShape.CONDITIONS_CHANGED
    return None


def _moves_people(before: ReleaseCondition | None, after: ReleaseCondition | None) -> bool:
    # A condition at 0% rollout serves nobody, so its override moves nobody.
    return _variant(before) != _variant(after) and any(
        condition is not None and condition.rollout > 0 for condition in (before, after)
    )


def _reordered(before: ReleaseConditions, after: ReleaseConditions, pairs: Mapping[int, int]) -> bool:
    # A person who matches two conditions gets the variant of the first one, the override or the hash's.
    serving = [
        (after_index, before_index)
        for after_index, before_index in sorted(pairs.items())
        if before[before_index].rollout > 0 and after[after_index].rollout > 0
    ]
    return any(
        first_before > second_before and after[first_after].variant != after[second_after].variant
        for (first_after, first_before), (second_after, second_before) in itertools.combinations(serving, 2)
    )


def _criteria_without(conditions: ReleaseConditions, ids: tuple[int, ...], touched: set[int]) -> list[str]:
    return sorted(condition.criteria for condition, condition_id in zip(conditions, ids) if condition_id not in touched)


def _variant(condition: ReleaseCondition | None) -> str | None:
    return condition.variant if condition is not None else None


def _looks_alike(old: ReleaseCondition, new: ReleaseCondition) -> bool:
    # Two conditions look alike when they match the same kind of thing: the same group type, and a shared property
    # key or no properties on either. Otherwise an unrelated new condition would read as an edit.
    if old.aggregation != new.aggregation:
        return False
    if not old.property_keys and not new.property_keys:
        return True
    return bool(old.property_keys & new.property_keys)


def _condition(group: object, flag_aggregation: int | None) -> ReleaseCondition:
    if not isinstance(group, dict):
        return ReleaseCondition(
            criteria=json.dumps(group, sort_keys=True, default=str),
            aggregation=None,
            property_keys=frozenset(),
            rollout=100,
            variant=None,
        )
    properties = group.get("properties")
    rollout = group.get("rollout_percentage")
    variant = group.get("variant")
    aggregation = condition_aggregation(group, flag_aggregation)
    return ReleaseCondition(
        criteria=json.dumps(
            [
                # A change of the flag-level aggregation is the bucketing check's to report, so a condition that
                # follows it keeps its criteria.
                _FOLLOWS_FLAG_AGGREGATION if aggregation == flag_aggregation else aggregation,
                # The filters of a condition all have to match, so their order does not matter.
                sorted(_property_signature(prop) for prop in properties) if isinstance(properties, list) else None,
            ],
            sort_keys=True,
            default=str,
        ),
        aggregation=_group_type_index(aggregation),
        property_keys=frozenset(_property_key(prop) for prop in properties)
        if isinstance(properties, list)
        else frozenset(),
        # The flag service reads a missing rollout as 100%.
        rollout=rollout if isinstance(rollout, int | float) and not isinstance(rollout, bool) else 100,
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


def _property_key(prop: object) -> str:
    if not isinstance(prop, dict):
        return json.dumps(prop, sort_keys=True, default=str)
    return f"{prop.get('type') or ''}:{prop.get('key') or ''}"


def _group_type_index(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
