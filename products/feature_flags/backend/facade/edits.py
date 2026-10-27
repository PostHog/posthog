"""What an edit of a feature flag does to who gets which value. Pure functions, no I/O.

Callers read the before and after values of a flag save, usually from the flag's activity log, and pass them
here. These functions own the flag service's rules for the variant split, the release conditions, and the
settings that decide a person's variant draw, so consumers don't derive them again.

Deliberately free of Django/DRF imports (same reason as ``facade.filters``): consumer model modules import
these at module level.
"""

import json
from collections import deque
from collections.abc import Callable, Collection, Hashable, Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from itertools import groupby

from posthog.dataclasses import frozen

from products.feature_flags.backend.facade.filters import condition_aggregation, pinned_variant

# Variants and the split
#
# The flag service draws a variant from a hash, and each variant is a slot of the split in stored order
# (`select_variant` in `rust/feature-flags/src/flags/v1_bucketing.rs`). A changed split moves the slot boundaries,
# so people whose hash lies between an old and a new boundary get another variant. A rollout change, or a
# release-condition change without a variant override, moves people into or out of the flag, never to another
# variant.


@frozen
class FlagVariant:
    key: str | None
    rollout_percentage: float | None


Split = tuple[FlagVariant, ...]


@frozen
class SplitChange:
    changed_at: datetime
    before: Split
    after: Split


def parse_variants(variants: object) -> Split:
    return tuple(_flag_variant(variant) for variant in variants) if isinstance(variants, list) else ()


def parse_percentage(value: object) -> float | None:
    # Only a JSON number is a percentage. A string or a boolean is not, and Python's `False == 0` would let a
    # boolean through.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def served_slots(split: Split) -> Split:
    # The flag service walks the cumulative percentages in order, so a variant at 0% has no range and serves
    # nobody. A percentage it can't read counts as served.
    return tuple(variant for variant in split if variant.rollout_percentage != 0)


def same_assignment(before: Split, after: Split) -> bool:
    """Whether both splits give every person the same variant."""
    return served_slots(before) == served_slots(after)


def rolled_out_variant_key(split: Split) -> str | None:
    # A holdout is drawn before the split with a hash of its own, so one variant at 100% is a rollout also
    # when the flag has a holdout.
    full = [variant for variant in split if variant.rollout_percentage == 100]
    return full[0].key if len(full) == 1 else None


def removed_variant_keys(before: Split, after: Split) -> list[str]:
    return _keys_missing_from(after, split=served_slots(before))


def added_variant_keys(before: Split, after: Split) -> list[str]:
    return _keys_missing_from(before, split=served_slots(after))


def zeroed_variant_keys(before: Split, after: Split) -> list[str]:
    served_before = {variant.key for variant in served_slots(before)}
    return [
        variant.key
        for variant in after
        if variant.key and variant.rollout_percentage == 0 and variant.key in served_before
    ]


def split_variant_keys(split: Split) -> tuple[str, ...]:
    return tuple(variant.key for variant in split if variant.key)


def _flag_variant(variant: object) -> FlagVariant:
    if not isinstance(variant, dict):
        return FlagVariant(key=None, rollout_percentage=None)
    key = variant.get("key")
    return FlagVariant(
        key=key if isinstance(key, str) else None,
        rollout_percentage=parse_percentage(variant.get("rollout_percentage")),
    )


def _keys_missing_from(other: Split, *, split: Split) -> list[str]:
    other_keys = {variant.key for variant in other}
    return [variant.key for variant in split if variant.key and variant.key not in other_keys]


# Release conditions
#
# A condition whose criteria change, or a condition that is added or removed, moves people into or out of the flag,
# never to another variant (`get_match` in rust/feature-flags/src/flags/flag_matching.rs). A variant override does
# move people: everyone a condition with an override matches gets that variant instead of the one from the hash.
# The flag service evaluates the conditions in order, so the order moves people who match two conditions that serve
# different variants.


@frozen
class ReleaseCondition:
    # The group type and property filters of the condition, as a signature that is equal for two conditions
    # that match the same people under the flag-level aggregation of their save. The rollout is not part of it.
    criteria: str
    # The group type index that the condition matches, None for persons, and the keys of its property filters.
    # The flag page's history pairs two conditions that share them as one condition edited.
    aggregation: int | None
    property_keys: frozenset[str]
    rollout: float
    variant: str | None


ReleaseConditions = tuple[ReleaseCondition, ...]


@frozen
class ConditionsChange:
    changed_at: datetime
    before: ReleaseConditions
    after: ReleaseConditions


_MAX_LOOK_ALIKES = 100
_FOLLOWS_FLAG_AGGREGATION = "flag"


def parse_release_conditions(
    groups: object, *, flag_aggregation: object = None, variant_keys: Collection[str]
) -> ReleaseConditions:
    """`variant_keys` are the variants of the flag in the same version, because the flag service ignores an
    override that names no variant of the flag."""
    aggregation = _group_type_index(flag_aggregation)
    return tuple(_condition(group, aggregation, variant_keys) for group in groups) if isinstance(groups, list) else ()


def pair_conditions(before: ReleaseConditions, after: ReleaseConditions) -> dict[int, int]:
    """
    The condition that each condition after a change was before it, as indexes from `after` to `before`. A
    condition without a pair was added or removed. The pairing is the one of the flag page's history
    (`diffReleaseConditionSets` in releaseConditionsDiff.ts): an unchanged condition first, then one with the same
    criteria, then a look-alike at the same position, then the only look-alike left.
    """
    pairs: dict[int, int] = {}
    paired: set[int] = set()

    def pair(after_index: int, before_index: int) -> None:
        pairs[after_index] = before_index
        paired.add(before_index)

    def pair_first_with_same(key: Callable[[ReleaseCondition], Hashable]) -> None:
        waiting: dict[Hashable, deque[int]] = {}
        for index, old in enumerate(before):
            if index not in paired:
                waiting.setdefault(key(old), deque()).append(index)
        for after_index, condition in enumerate(after):
            candidates = waiting.get(key(condition))
            if after_index not in pairs and candidates:
                pair(after_index, candidates.popleft())

    pair_first_with_same(lambda condition: condition)
    pair_first_with_same(lambda condition: condition.criteria)
    unpaired_after = [index for index in range(len(after)) if index not in pairs]
    unpaired_before = [index for index in range(len(before)) if index not in paired]
    # Look-alikes are compared each with each. A save that edits more conditions than this pairs no more of them,
    # so they count as removed and added, which bounds the work for a flag with very many conditions.
    if len(unpaired_after) > _MAX_LOOK_ALIKES or len(unpaired_before) > _MAX_LOOK_ALIKES:
        return pairs
    for after_index in unpaired_after:
        if (
            after_index < len(before)
            and after_index not in paired
            and _looks_alike(before[after_index], after[after_index])
        ):
            pair(after_index, after_index)
    # A condition that was edited and moved in one save has no partner at its position. It pairs with the one
    # condition left that it looks like. With several, no pair is safe, so they count as removed and added.
    for after_index in unpaired_after:
        if after_index in pairs:
            continue
        candidates = [
            index
            for index in unpaired_before
            if index not in paired and _looks_alike(before[index], after[after_index])
        ]
        if len(candidates) == 1:
            pair(after_index, candidates[0])
    return pairs


def moves_people(before: ReleaseCondition | None, after: ReleaseCondition | None) -> bool:
    """Whether a condition's change of override moves the people it matches to another variant."""
    # A condition at 0% rollout serves nobody, so its override moves nobody.
    return _variant(before) != _variant(after) and any(
        condition is not None and condition.rollout > 0 for condition in (before, after)
    )


def order_moves_people(before: ReleaseConditions, after: ReleaseConditions, pairs: Mapping[int, int]) -> bool:
    """Whether the new order gives a person who matches two conditions another variant. `pairs` are the pairs
    of `pair_conditions`."""
    # A person who matches two conditions gets the variant of the first one, the override or the hash's. Walking
    # the conditions in their new order, a condition moved ahead of one with another variant when that one sat
    # later before the change. Keeping the latest position and the latest of any other variant finds it in one pass.
    latest: tuple[int, str | None] | None = None
    latest_of_other_variant = -1
    for after_index, before_index in sorted(pairs.items()):
        if before[before_index].rollout <= 0 or after[after_index].rollout <= 0:
            continue
        variant = after[after_index].variant
        if latest is not None:
            latest_position, latest_variant = latest
            if (latest_position if latest_variant != variant else latest_of_other_variant) > before_index:
                return True
            if variant == latest_variant:
                latest = (max(latest_position, before_index), variant)
            elif before_index > latest_position:
                latest_of_other_variant = latest_position
                latest = (before_index, variant)
            else:
                latest_of_other_variant = max(latest_of_other_variant, before_index)
        else:
            latest = (before_index, variant)
    return False


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


def _condition(group: object, flag_aggregation: int | None, variant_keys: Collection[str]) -> ReleaseCondition:
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
    aggregation = condition_aggregation(group, flag_aggregation)
    return ReleaseCondition(
        criteria=json.dumps(
            [
                # A change of the flag-level aggregation is a bucketing change, so a condition that follows it keeps
                # its criteria.
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
        variant=pinned_variant(group, variant_keys),
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


# Bucketing
#
# The flag service hashes the flag key with an identifier: the group key for a flag that aggregates by a group type,
# otherwise the device ID or the distinct ID, as `bucketing_identifier` says, and with experience continuity the
# person's stored anonymous ID (`hashed_identifier` in rust/feature-flags/src/flags/flag_matching.rs). A change of any
# of them gives the people it touches a new draw, so they can get another variant.


class BucketingSetting(StrEnum):
    # The flag settings besides the split that are inputs of the variant draw. The functions below return changes
    # in this order, and callers rely on it.
    KEY = "key"
    AGGREGATION = "aggregation"
    BUCKETING_IDENTIFIER = "bucketing_identifier"
    EXPERIENCE_CONTINUITY = "experience_continuity"


@frozen
class BucketingChange:
    changed_at: datetime
    setting: BucketingSetting
    # The key as a string, the aggregation as a group type index or None for persons, the identifier as
    # "distinct_id" or "device_id", the continuity as a bool.
    before: str | int | bool | None
    after: str | int | bool | None


def bucketing_changes_from_activity(
    *,
    changed_at: datetime,
    feature_flag_id: int,
    before: Mapping[BucketingSetting, object],
    after: Mapping[BucketingSetting, object],
) -> list[BucketingChange]:
    """The bucketing changes in one activity log row of the flag. A setting the row does not change is absent."""
    changes = []
    for setting in BucketingSetting:
        value_before = _normalized(setting, before.get(setting), feature_flag_id)
        value_after = _normalized(setting, after.get(setting), feature_flag_id)
        if value_before != value_after:
            changes.append(
                BucketingChange(changed_at=changed_at, setting=setting, before=value_before, after=value_after)
            )
    return changes


def conditions_follow_flag_aggregation(aggregation: object, conditions: Sequence[object]) -> bool:
    """
    Whether no release condition aggregates by person while the flag-level aggregation names a group type.
    `changes_that_apply` relies on this, because it reads only the flag-level aggregation of each save. The flag
    serializer keeps it true: it sets the flag-level aggregation to null when the conditions mix aggregations.
    """
    flag_aggregation = _group_type_index(aggregation)
    return flag_aggregation is None or all(
        condition_aggregation(condition, flag_aggregation) is not None
        for condition in conditions
        if isinstance(condition, dict)
    )


def changes_that_apply(
    changes: Sequence[BucketingChange],
    *,
    feature_flag_id: int,
    aggregation: object,
    bucketing_identifier: object,
    trust_flag_aggregation: bool,
) -> tuple[BucketingChange, ...]:
    """
    The changes as the flag service reads them, save by save. It hashes the group key for a flag that aggregates by
    a group type, so it does not read the bucketing identifier and persistence there. It hashes the device ID before
    it reads persistence, so it does not read persistence under device ID bucketing either.

    A setting that changes while the flag service does not read it moves nobody at that save. The new value takes
    effect at the save after which the flag service reads the setting again, so the change counts there, from the
    value that the flag service read last.

    `aggregation` and `bucketing_identifier` are the flag's current values. When `trust_flag_aggregation` is false,
    a release condition can aggregate by person under any flag-level aggregation, so the flag-level aggregation does
    not stop the flag service from reading the identifier.
    """
    state: dict[BucketingSetting, str | int | bool | None] = {
        BucketingSetting.AGGREGATION: _normalized(BucketingSetting.AGGREGATION, aggregation, feature_flag_id),
        BucketingSetting.BUCKETING_IDENTIFIER: _normalized(
            BucketingSetting.BUCKETING_IDENTIFIER, bucketing_identifier, feature_flag_id
        ),
    }
    # Each setting holds the `before` of its first change until that change, and its current value without one.
    for change in reversed(changes):
        state[change.setting] = change.before

    def reads(setting: BucketingSetting) -> bool:
        by_person = state[BucketingSetting.AGGREGATION] is None or not trust_flag_aggregation
        match setting:
            case BucketingSetting.BUCKETING_IDENTIFIER:
                return by_person
            case BucketingSetting.EXPERIENCE_CONTINUITY:
                return by_person and state[BucketingSetting.BUCKETING_IDENTIFIER] == "distinct_id"
            case _:
                return True

    last_read = {setting: value for setting, value in state.items() if reads(setting)}
    applied = []
    for changed_at, saved in groupby(changes, key=lambda change: change.changed_at):
        for change in saved:
            state[change.setting] = change.after
        for setting in BucketingSetting:
            if setting not in state or not reads(setting):
                continue
            # A setting that the flag service never read before has no earlier value to count from. The change
            # that made the flag service read it, such as an aggregation change, counts instead.
            if setting in last_read and last_read[setting] != state[setting]:
                applied.append(
                    BucketingChange(
                        changed_at=changed_at, setting=setting, before=last_read[setting], after=state[setting]
                    )
                )
            last_read[setting] = state[setting]
    return tuple(applied)


def _normalized(setting: BucketingSetting, value: object, feature_flag_id: int) -> str | int | bool | None:
    # Each setting is read the way the flag service reads it, so a save that writes the default explicitly is
    # no change.
    match setting:
        case BucketingSetting.KEY:
            if not isinstance(value, str):
                return None
            # Soft-deleting a flag appends this suffix to its key (`FeatureFlag.tombstoned_key`), and restoring it
            # removes the suffix again. Neither is a new key.
            tombstone = f":deleted:{feature_flag_id}"
            return value.removesuffix(tombstone)
        case BucketingSetting.AGGREGATION:
            return _group_type_index(value)
        case BucketingSetting.BUCKETING_IDENTIFIER:
            return "device_id" if value == "device_id" else "distinct_id"
        case BucketingSetting.EXPERIENCE_CONTINUITY:
            return value is True


def _group_type_index(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
