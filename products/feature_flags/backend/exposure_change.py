"""Whether an edit of a feature flag raises, lowers, or keeps the share of people who get a value of the flag.

Flag rollback suggestions watch the errors after an edit that raises exposure, and the flag page asks why after an
edit that lowers it. Both read the edit here, so they agree on its direction. An edit is a change to the flag's
`filters` or `active`. The flag's `version` also changes when a cohort or a flag that the flag uses changes, so it is
not an input.

Not covered: the holdout, because only experiments write it, and their flags are out of scope. The bucketing
settings, because they give people a new draw without a change of the share. A change of `early_exit`. Conditions
that no request reaches, such as a condition after one that matches everybody.
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
    moves_people,
    order_moves_people,
    pair_conditions,
    parse_release_conditions,
    parse_variants,
    same_assignment,
    served_slots,
    split_variant_keys,
)


class ExposureChangeKind(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    ROLLOUT_INCREASED = "rollout_increased"
    ROLLOUT_DECREASED = "rollout_decreased"
    CONDITION_ADDED = "condition_added"
    CONDITION_REMOVED = "condition_removed"
    # The criteria of a condition changed, or the flag-level aggregation changed. Such an edit can give the flag to new
    # people and take it from others.
    PROPERTIES_CHANGED = "properties_changed"
    # With early exit, the order of the conditions decides which condition gives a person false, so a new order can
    # give the flag to new people and take it from others.
    CONDITIONS_REORDERED = "conditions_reordered"
    # The split, a variant override, or the order of conditions with different variants changed, or people that a
    # condition no longer serves fall through to a later condition with another variant. Some people get another
    # variant.
    VARIANT_CHANGED = "variant_changed"


class ExposureDirection(StrEnum):
    RAISES = "raises"
    LOWERS = "lowers"
    KEEPS = "keeps"


@frozen
class FlagExposureConfig:
    """The fields of a flag on one side of an edit that decide who gets which value."""

    active: bool
    filters: Mapping[str, Any] | None


@frozen
class ExposureChange:
    kinds: frozenset[ExposureChangeKind]
    # True when people who got false before the edit can get a value of the flag after it. Their curve is the share
    # of people with any value other than false, so `grown_variants` leaves them out.
    reaches_new_people: bool
    # True when people who got a value before the edit can get false after it.
    loses_people: bool
    # The variants that people who already got a value can get instead of the one they had, one curve each. Empty when
    # the flag is boolean after the edit, so a variant change there means that people who got a variant get `true` now.
    grown_variants: tuple[str, ...]
    # The flag-level group type index after the edit, None for persons. A group flag counts groups, not people.
    aggregation: int | None

    @property
    def direction(self) -> ExposureDirection:
        # An edit that raises exposure for some people and lowers it for others can cause new errors, so it raises.
        if self.reaches_new_people or ExposureChangeKind.VARIANT_CHANGED in self.kinds:
            return ExposureDirection.RAISES
        if self.loses_people:
            return ExposureDirection.LOWERS
        return ExposureDirection.KEEPS


@frozen
class _Side:
    split: Split
    conditions: ReleaseConditions
    aggregation: int | None
    early_exit: bool


class _ChangeBuilder:
    def __init__(self) -> None:
        self._kinds: set[ExposureChangeKind] = set()
        self._reaches_new_people = False
        self._loses_people = False
        # A dict keeps the first order in which each variant grew, so the result is stable.
        self._grown_variants: dict[str, None] = {}

    def add(
        self,
        kind: ExposureChangeKind,
        *,
        reaches_new_people: bool = False,
        loses_people: bool = False,
        grown_variants: tuple[str, ...] = (),
    ) -> None:
        self._kinds.add(kind)
        self._reaches_new_people = self._reaches_new_people or reaches_new_people
        self._loses_people = self._loses_people or loses_people
        self._grown_variants.update(dict.fromkeys(grown_variants))

    def build(self, *, aggregation: int | None) -> ExposureChange:
        return ExposureChange(
            kinds=frozenset(self._kinds),
            reaches_new_people=self._reaches_new_people,
            loses_people=self._loses_people,
            grown_variants=tuple(self._grown_variants),
            aggregation=aggregation,
        )


def _served_keys(split: Split, *, without: str | None) -> tuple[str, ...]:
    return tuple(variant.key for variant in served_slots(split) if variant.key and variant.key != without)


@frozen
class _HashRange:
    start: float
    end: float

    def contains(self, other: "_HashRange") -> bool:
        return self.start <= other.start and other.end <= self.end


def _hash_ranges(split: Split) -> dict[str, _HashRange]:
    # The flag service gives each variant the hash values from the sum of the variants before it, in stored order.
    ranges: dict[str, _HashRange] = {}
    start = 0.0
    for variant in served_slots(split):
        width = variant.rollout_percentage or 0.0
        if variant.key:
            ranges.setdefault(variant.key, _HashRange(start=start, end=start + width))
        start += width
    return ranges


def _grown_split_variants(old: Split, new: Split) -> tuple[str, ...]:
    # A variant gets new people when its new range reaches outside its old one. That is also true for a variant whose
    # share shrinks, and for every variant of a new order with the same shares.
    before = _hash_ranges(old)
    return tuple(
        key
        for key, hash_range in _hash_ranges(new).items()
        if key not in before or not before[key].contains(hash_range)
    )


def _serves_any_of(conditions: ReleaseConditions) -> bool:
    return any(condition.rollout > 0 for condition in conditions)


def _serves_anybody(side: _Side) -> bool:
    return _serves_any_of(side.conditions)


def _stops_people(condition: ReleaseCondition, side: _Side) -> bool:
    # With early exit, a person whose properties match a condition and whose hash is outside its rollout gets false,
    # and the flag service reads no later condition for them (`get_match` in rust/feature-flags/src/flags/
    # flag_matching.rs). A condition at 0% then still decides who gets false.
    return side.early_exit and condition.rollout < 100


def _serves_from_split(side: _Side) -> bool:
    return any(condition.rollout > 0 and condition.variant is None for condition in side.conditions)


def _fallthrough_variants(later: ReleaseConditions, split: Split, *, released: str | None) -> tuple[str, ...]:
    # The flag service evaluates the conditions in order, so the people that a condition no longer serves get the
    # value of the next condition that matches them.
    grown: dict[str, None] = {}
    for condition in later:
        if condition.rollout > 0 and condition.variant != released:
            keys = (condition.variant,) if condition.variant else _served_keys(split, without=released)
            grown.update(dict.fromkeys(keys))
    return tuple(grown)


def _captured_variants(condition: ReleaseCondition, later: ReleaseConditions, split: Split) -> tuple[str, ...]:
    # A new condition serves the people it matches before the later conditions do, so people that a later condition
    # with another variant served get the variant of the new condition.
    if not any(other.rollout > 0 and other.variant != condition.variant for other in later):
        return ()
    return (condition.variant,) if condition.variant else _served_keys(split, without=None)


def _side(filters: Mapping[str, Any] | None) -> _Side:
    filters = filters or {}
    multivariate = filters.get("multivariate")
    split = parse_variants(multivariate.get("variants") if isinstance(multivariate, Mapping) else None)
    aggregation = filters.get("aggregation_group_type_index")
    aggregation = aggregation if isinstance(aggregation, int) and not isinstance(aggregation, bool) else None
    return _Side(
        # The flag service reads a missing value as false.
        early_exit=filters.get("early_exit") is True,
        split=split,
        conditions=parse_release_conditions(
            filters.get("groups"), flag_aggregation=aggregation, variant_keys=split_variant_keys(split)
        ),
        aggregation=aggregation,
    )


def _add_fallthrough(builder: _ChangeBuilder, later: ReleaseConditions, split: Split, *, released: str | None) -> None:
    grown = _fallthrough_variants(later, split, released=released)
    if grown:
        builder.add(ExposureChangeKind.VARIANT_CHANGED, grown_variants=grown)


def _compare_pair(
    previous: ReleaseCondition,
    condition: ReleaseCondition,
    *,
    new_index: int,
    old: _Side,
    new: _Side,
    builder: _ChangeBuilder,
) -> None:
    decides_before = previous.rollout > 0 or _stops_people(previous, old)
    decides_after = condition.rollout > 0 or _stops_people(condition, new)
    if not decides_before and not decides_after:
        return
    releases_people = False
    if previous.criteria != condition.criteria:
        builder.add(
            ExposureChangeKind.PROPERTIES_CHANGED,
            reaches_new_people=condition.rollout > 0 or _stops_people(previous, old),
            loses_people=previous.rollout > 0 or _stops_people(condition, new),
        )
        releases_people = True
    if condition.rollout > previous.rollout:
        builder.add(ExposureChangeKind.ROLLOUT_INCREASED, reaches_new_people=True)
    elif condition.rollout < previous.rollout:
        builder.add(ExposureChangeKind.ROLLOUT_DECREASED, loses_people=True)
        releases_people = releases_people or not _stops_people(condition, new)
    if releases_people:
        _add_fallthrough(builder, new.conditions[new_index + 1 :], new.split, released=previous.variant)
    if condition.rollout > 0 and moves_people(previous, condition):
        # Without an override after the edit, the people the condition matches get a variant from the split.
        grown = (condition.variant,) if condition.variant else _served_keys(new.split, without=previous.variant)
        builder.add(ExposureChangeKind.VARIANT_CHANGED, grown_variants=grown)


def _compare_added(condition: ReleaseCondition, *, new_index: int, new: _Side, builder: _ChangeBuilder) -> None:
    if condition.rollout <= 0 and not _stops_people(condition, new):
        return
    later = new.conditions[new_index + 1 :]
    builder.add(
        ExposureChangeKind.CONDITION_ADDED,
        reaches_new_people=condition.rollout > 0,
        # The people the new condition stops got the value of a later condition before.
        loses_people=_stops_people(condition, new) and _serves_any_of(later),
        grown_variants=_captured_variants(condition, later, new.split) if condition.rollout > 0 else (),
    )


def _compare_removed(
    removed: ReleaseCondition, *, old_index: int, pairs: dict[int, int], old: _Side, new: _Side, builder: _ChangeBuilder
) -> None:
    if removed.rollout <= 0 and not _stops_people(removed, old):
        return
    later = tuple(new.conditions[new_index] for new_index, paired in sorted(pairs.items()) if paired > old_index)
    builder.add(
        ExposureChangeKind.CONDITION_REMOVED,
        # The people the removed condition stopped get the value of a later condition now.
        reaches_new_people=_stops_people(removed, old) and _serves_any_of(later),
        loses_people=removed.rollout > 0,
    )
    _add_fallthrough(builder, later, new.split, released=removed.variant)


def _order_moves_stops(new: _Side, pairs: dict[int, int]) -> bool:
    # With early exit, a condition that stops people decides only for the people who reach it, so a new order changes
    # who it stops.
    if not new.early_exit:
        return False
    order = [pairs[new_index] for new_index in sorted(pairs)]
    reordered = any(earlier > later for earlier, later in zip(order, order[1:]))
    return reordered and any(_stops_people(new.conditions[new_index], new) for new_index in pairs)


def _compare_conditions(old: _Side, new: _Side, builder: _ChangeBuilder) -> None:
    pairs = pair_conditions(old.conditions, new.conditions)
    for new_index, condition in enumerate(new.conditions):
        if new_index in pairs:
            previous = old.conditions[pairs[new_index]]
            _compare_pair(previous, condition, new_index=new_index, old=old, new=new, builder=builder)
        else:
            _compare_added(condition, new_index=new_index, new=new, builder=builder)

    paired_before = set(pairs.values())
    for old_index, removed in enumerate(old.conditions):
        if old_index not in paired_before:
            _compare_removed(removed, old_index=old_index, pairs=pairs, old=old, new=new, builder=builder)
    if _order_moves_stops(new, pairs):
        builder.add(ExposureChangeKind.CONDITIONS_REORDERED, reaches_new_people=True, loses_people=True)
    if order_moves_people(old.conditions, new.conditions, pairs):
        # The order moves the people who match two conditions to the variant of the condition that comes first now.
        # Which conditions those are is not known here, so every variant can grow.
        builder.add(ExposureChangeKind.VARIANT_CHANGED, grown_variants=_served_keys(new.split, without=None))


def classify_exposure_change(*, before: FlagExposureConfig, after: FlagExposureConfig) -> ExposureChange:
    """Raises `ConfigFormatError` for a config that is not version 1."""
    require_v1_config(before.filters)
    require_v1_config(after.filters)
    old = _side(before.filters)
    new = _side(after.filters)
    builder = _ChangeBuilder()

    # A disabled flag serves nobody, so an edit of a disabled flag changes nothing until the flag is enabled.
    if not before.active or not after.active:
        if not before.active and after.active and _serves_anybody(new):
            builder.add(ExposureChangeKind.ENABLED, reaches_new_people=True)
        if before.active and not after.active and _serves_anybody(old):
            builder.add(ExposureChangeKind.DISABLED, loses_people=True)
        return builder.build(aggregation=new.aggregation)

    if old.aggregation != new.aggregation and _serves_anybody(new):
        builder.add(ExposureChangeKind.PROPERTIES_CHANGED, reaches_new_people=True, loses_people=True)
    _compare_conditions(old, new, builder)
    if not same_assignment(old.split, new.split) and _serves_from_split(new):
        builder.add(ExposureChangeKind.VARIANT_CHANGED, grown_variants=_grown_split_variants(old.split, new.split))
    return builder.build(aggregation=new.aggregation)
