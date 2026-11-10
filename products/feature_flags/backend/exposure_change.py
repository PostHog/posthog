"""Whether an edit of a feature flag raises, lowers, or keeps the share of people who get a value of the flag.

Flag rollback suggestions watch the errors after an edit that raises exposure, and the flag page asks why after an
edit that lowers it. Both read the edit here, so they agree on its direction. An edit is a change to the flag's
`filters`, `active`, `deleted`, key, bucketing identifier or experience continuity. The flag's `version` also changes
when a cohort or a flag that the flag uses changes, so it is not an input.

The flag service gives each person the value of the first condition that matches them. Which people match two
conditions depends on the data, not on the config, so the config alone cannot tell who gets another value. The
classification is therefore conservative. An edit lowers exposure only when it takes values away and gives nobody
another value. Any other edit that can change who gets which value raises it. A raise that reaches nobody costs
little, because the rollback suggestion then finds nobody with a new value and stops watching the errors. A missed
raise lets a bad rollout through.

Not covered: the holdout, because only experiments write it, and their flags are out of scope. Early access enrollment
and the other super groups, because the early access product owns those flags. Turning `early_exit` on, which takes
values away from the people outside a condition's rollout. It changes how the conditions combine and rolls nothing
back, so the flag page does not ask why. The flag-level aggregation is covered, because it decides whether the flag
counts persons or groups.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from posthog.dataclasses import frozen

from products.feature_flags.backend.facade.config import require_v1_config
from products.feature_flags.backend.facade.edits import (
    ReleaseCondition,
    ReleaseConditions,
    Split,
    group_type_index,
    moves_people,
    normalized_bucketing_identifier,
    normalized_experience_continuity,
    pair_conditions,
    parse_release_conditions,
    parse_variants,
    same_assignment,
    served_slots,
    split_variant_keys,
)


class ExposureChangeKind(StrEnum):
    # The flag was enabled or restored.
    ENABLED = "enabled"
    # The flag was disabled or deleted.
    DISABLED = "disabled"
    ROLLOUT_INCREASED = "rollout_increased"
    ROLLOUT_DECREASED = "rollout_decreased"
    CONDITION_ADDED = "condition_added"
    CONDITION_REMOVED = "condition_removed"
    # The criteria of a condition changed, or the flag-level aggregation changed.
    CRITERIA_CHANGED = "criteria_changed"
    VARIANT_CHANGED = "variant_changed"
    # The conditions have a new order, and the order decides the value of a person who matches two of them.
    CONDITIONS_REORDERED = "conditions_reordered"
    # A person whose properties match a condition and whose hash is outside its rollout now gets the value of a later
    # condition, not false.
    EARLY_EXIT_TURNED_OFF = "early_exit_turned_off"
    # The flag key, the bucketing identifier or experience continuity changed, so the hash gives people a new draw.
    BUCKETING_CHANGED = "bucketing_changed"


_LOWERING_KINDS = frozenset(
    {ExposureChangeKind.DISABLED, ExposureChangeKind.ROLLOUT_DECREASED, ExposureChangeKind.CONDITION_REMOVED}
)


class ExposureDirection(StrEnum):
    RAISES = "raises"
    LOWERS = "lowers"
    KEEPS = "keeps"


@frozen
class FlagExposureConfig:
    """The fields of a flag on one side of an edit that decide who gets which value."""

    active: bool
    filters: Mapping[str, Any] | None
    key: str
    bucketing_identifier: str | None
    ensure_experience_continuity: bool | None
    deleted: bool = False


@frozen
class ExposureChange:
    kinds: frozenset[ExposureChangeKind]
    direction: ExposureDirection
    # The variants that the flag can serve after the edit, from the split and from the variant overrides. After a
    # raise, the rollback suggestion counts the people with any value other than false, and the people with each
    # variant. Empty for a boolean flag, and for a disabled or deleted flag.
    served_variants: tuple[str, ...]


@frozen
class _Side:
    split: Split
    conditions: ReleaseConditions
    aggregation: int | None
    early_exit: bool
    buckets_on_device_id: bool


class _ChangeBuilder:
    def __init__(self) -> None:
        self._kinds: set[ExposureChangeKind] = set()
        self._raises = False

    def add(self, kind: ExposureChangeKind, *, gives_another_value: bool = False) -> None:
        self._kinds.add(kind)
        self._raises = self._raises or kind not in _LOWERING_KINDS or gives_another_value

    def direction(self) -> ExposureDirection:
        if self._raises:
            return ExposureDirection.RAISES
        if self._kinds:
            return ExposureDirection.LOWERS
        return ExposureDirection.KEEPS

    def kinds(self) -> frozenset[ExposureChangeKind]:
        return frozenset(self._kinds)


def _serves_anybody(side: _Side) -> bool:
    return any(condition.rollout > 0 for condition in side.conditions)


def _serves_from_split(side: _Side) -> bool:
    return any(condition.rollout > 0 and condition.variant is None for condition in side.conditions)


def _served_variants(side: _Side) -> tuple[str, ...]:
    variants: dict[str, None] = {}
    if _serves_from_split(side):
        variants.update(dict.fromkeys(variant.key for variant in served_slots(side.split) if variant.key))
    variants.update(
        dict.fromkeys(condition.variant for condition in side.conditions if condition.rollout > 0 and condition.variant)
    )
    return tuple(variants)


def _ends_evaluation(condition: ReleaseCondition, side: _Side) -> bool:
    # A condition ends the evaluation for the people whose properties match it and whose hash is inside its rollout.
    # With early exit, it also ends the evaluation for the people outside its rollout: they get false, and the flag
    # service reads no later condition for them.
    # See `get_match` in rust/feature-flags/src/flags/flag_matching.rs.
    # A condition at 0% then still decides who gets false.
    return condition.rollout > 0 or side.early_exit


def _gives_false_outside_rollout(condition: ReleaseCondition, side: _Side) -> bool:
    # The value of a later condition then does not reach the people that this condition matches outside its rollout.
    return side.early_exit and condition.rollout < 100


# The variant override of a condition, or None with the group type whose key the split hashes.
_Value = tuple[str | None, int | None]


def _value(condition: ReleaseCondition, side: _Side) -> _Value:
    # The split hashes the group key for a group condition and the person for a person condition, so two conditions
    # of different group types give a person different draws of the same split. A boolean flag serves true for both.
    if condition.variant or not served_slots(side.split):
        return (condition.variant, None)
    return (None, condition.aggregation)


def _gives_another_value(old_condition: ReleaseCondition, new: _Side, served_after: set[_Value]) -> bool:
    # A person that `old_condition` no longer serves gets the value of a later condition that matches them, which can
    # differ from the value `old_condition` gave them. Positions are not compared, so a served condition anywhere in
    # the flag counts, which errs toward a raise.
    old_value = _value(old_condition, new)
    return any(value != old_value for value in served_after)


def _needs_bucketing_hash(condition: ReleaseCondition, side: _Side) -> bool:
    # The same rule as `condition_needs_bucketing_hash` in rust/feature-flags/src/flags/flag_operations.rs. The hash
    # decides the result of a condition below 100%. It also decides the result of a condition that serves from a
    # split whose first served variant is below 100%, because a hash past that variant gets another variant, or true
    # when the split covers less than 100%. Under device ID bucketing, the flag service skips a person condition that
    # needs the hash for a request without a device ID, a condition at 0% included.
    if condition.rollout < 100:
        return True
    slots = served_slots(side.split)
    if not slots or condition.variant is not None:
        return False
    first = slots[0].rollout_percentage
    return first is None or first < 100


def _skipped_without_device_id(condition: ReleaseCondition, side: _Side) -> bool:
    return side.buckets_on_device_id and condition.aggregation is None and _needs_bucketing_hash(condition, side)


def _reads_bucketing(side: _Side, *, persons_only: bool = False) -> bool:
    # A condition that ends the evaluation for nobody gives the same result whatever the hash is. A condition at 0%
    # with early exit counts, which errs toward a raise for a new key: the hash does not change its result, but a
    # change to device ID bucketing makes the flag service skip it.
    return any(
        _ends_evaluation(condition, side) and _needs_bucketing_hash(condition, side)
        for condition in side.conditions
        if not persons_only or condition.aggregation is None
    )


def _person_hash_inputs(config: FlagExposureConfig, side: _Side) -> tuple[str, bool]:
    identifier = normalized_bucketing_identifier(config.bucketing_identifier)
    # The flag service reads experience continuity only for a person flag that buckets on the distinct ID. See
    # `has_experience_continuity` in rust/feature-flags/src/flags/flag_operations.rs.
    continuity = (
        identifier == "distinct_id"
        and side.aggregation is None
        and normalized_experience_continuity(config.ensure_experience_continuity)
    )
    return identifier, continuity


def _changes_bucketing(before: FlagExposureConfig, after: FlagExposureConfig, old: _Side, new: _Side) -> bool:
    # The flag service hashes the flag key with the group key for a group condition. For a person condition, it uses
    # the device ID or the distinct ID, as the bucketing identifier says. With experience continuity, it uses an
    # override row or the anonymous ID that the request sends. See `hashed_identifier` in
    # rust/feature-flags/src/flags/flag_matching.rs. Turning continuity on also moves people, because the request's
    # anonymous ID and the override rows from an earlier period of continuity then replace the distinct ID.
    # A deleted flag does not get here, so the tombstone suffix of a deleted flag's key is not a new key.
    if before.key != after.key and _reads_bucketing(new):
        return True
    return _person_hash_inputs(before, old) != _person_hash_inputs(after, new) and _reads_bucketing(
        new, persons_only=True
    )


def _reordered(pairs: Mapping[int, int]) -> bool:
    order = [pairs[new_index] for new_index in sorted(pairs)]
    return any(earlier > later for earlier, later in zip(order, order[1:]))


def _side(config: FlagExposureConfig) -> _Side:
    filters = config.filters or {}
    multivariate = filters.get("multivariate")
    split = parse_variants(multivariate.get("variants") if isinstance(multivariate, Mapping) else None)
    aggregation = group_type_index(filters.get("aggregation_group_type_index"))
    return _Side(
        split=split,
        conditions=parse_release_conditions(
            filters.get("groups"), flag_aggregation=aggregation, variant_keys=split_variant_keys(split)
        ),
        aggregation=aggregation,
        early_exit=filters.get("early_exit") is True,
        buckets_on_device_id=normalized_bucketing_identifier(config.bucketing_identifier) == "device_id",
    )


def _compare_pair(
    previous: ReleaseCondition,
    condition: ReleaseCondition,
    *,
    old: _Side,
    new: _Side,
    served_after: set[_Value],
    builder: _ChangeBuilder,
) -> None:
    if not _ends_evaluation(previous, old) and not _ends_evaluation(condition, new):
        return
    if previous.criteria != condition.criteria and _ends_evaluation(condition, new):
        builder.add(ExposureChangeKind.CRITERIA_CHANGED)
    if condition.rollout > previous.rollout:
        builder.add(ExposureChangeKind.ROLLOUT_INCREASED)
    elif condition.rollout < previous.rollout:
        # With early exit, the people outside the new rollout get false, not the value of a later condition. A request
        # that skips the condition for a missing device ID can still get that value.
        builder.add(
            ExposureChangeKind.ROLLOUT_DECREASED,
            gives_another_value=(not new.early_exit or _skipped_without_device_id(condition, new))
            and _gives_another_value(previous, new, served_after),
        )
    if condition.rollout > 0 and moves_people(previous, condition):
        builder.add(ExposureChangeKind.VARIANT_CHANGED)


def _compare_conditions(old: _Side, new: _Side, builder: _ChangeBuilder) -> None:
    pairs = pair_conditions(old.conditions, new.conditions)
    served_after = {_value(condition, new) for condition in new.conditions if condition.rollout > 0}
    for new_index, condition in enumerate(new.conditions):
        if new_index in pairs:
            previous = old.conditions[pairs[new_index]]
            _compare_pair(previous, condition, old=old, new=new, served_after=served_after, builder=builder)
        elif _ends_evaluation(condition, new):
            builder.add(ExposureChangeKind.CONDITION_ADDED)

    paired_before = set(pairs.values())
    for old_index, removed in enumerate(old.conditions):
        if old_index in paired_before or not _ends_evaluation(removed, old):
            continue
        # With early exit, the people that the removed condition gave false can get the value of a later condition.
        builder.add(
            ExposureChangeKind.CONDITION_REMOVED,
            gives_another_value=_gives_false_outside_rollout(removed, old)
            or _gives_another_value(removed, new, served_after),
        )

    # A new order gives a person who matches two conditions the value of the one that comes first now. Which pairs
    # of conditions overlap is not known here, so any reorder of conditions with different values counts, and so does
    # a reorder of a condition that gives false outside its rollout. A condition that ends the evaluation for nobody
    # on either side cannot move anybody.
    deciding = {
        new_index: old_index
        for new_index, old_index in pairs.items()
        if _ends_evaluation(new.conditions[new_index], new) and _ends_evaluation(old.conditions[old_index], old)
    }
    kept_values = {
        _value(new.conditions[new_index], new) for new_index in deciding if new.conditions[new_index].rollout > 0
    }
    gives_false = any(_gives_false_outside_rollout(new.conditions[new_index], new) for new_index in deciding)
    if _reordered(deciding) and (gives_false or len(kept_values) > 1):
        builder.add(ExposureChangeKind.CONDITIONS_REORDERED)


def classify_exposure_change(*, before: FlagExposureConfig, after: FlagExposureConfig) -> ExposureChange:
    """Raises `ConfigFormatError` for a config that is not version 1."""
    require_v1_config(before.filters)
    require_v1_config(after.filters)
    old = _side(before)
    new = _side(after)
    # A disabled or deleted flag serves nobody, so an edit of one changes nothing until the flag is enabled or
    # restored. See the `deleted = false` filter in rust/feature-flags/src/flags/feature_flag_list.rs.
    was_on = before.active and not before.deleted
    is_on = after.active and not after.deleted
    builder = _ChangeBuilder()

    if was_on and is_on:
        if old.aggregation != new.aggregation and _serves_anybody(new):
            builder.add(ExposureChangeKind.CRITERIA_CHANGED)
        if (
            not new.early_exit
            and any(_gives_false_outside_rollout(condition, old) for condition in old.conditions)
            and _serves_anybody(new)
        ):
            builder.add(ExposureChangeKind.EARLY_EXIT_TURNED_OFF)
        if _changes_bucketing(before, after, old, new):
            builder.add(ExposureChangeKind.BUCKETING_CHANGED)
        _compare_conditions(old, new, builder)
        if not same_assignment(old.split, new.split) and _serves_from_split(new):
            builder.add(ExposureChangeKind.VARIANT_CHANGED)
    elif is_on and _serves_anybody(new):
        builder.add(ExposureChangeKind.ENABLED)
    elif was_on and _serves_anybody(old):
        builder.add(ExposureChangeKind.DISABLED)

    return ExposureChange(
        kinds=builder.kinds(),
        direction=builder.direction(),
        served_variants=_served_variants(new) if is_on else (),
    )
