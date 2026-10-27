"""Whether an edit of a feature flag raises, lowers, or keeps the share of people who get a value of the flag.

Flag rollback suggestions watch the errors after an edit that raises exposure, and the flag page asks why after an
edit that lowers it. Both read the edit here, so they agree on its direction. An edit is a change to the flag's
`filters` or `active`. The flag's `version` also changes when a cohort or a flag that the flag uses changes, so it is
not an input.

The flag service gives each person the value of the first condition that matches them. Which people match two
conditions depends on the data, not on the config, so the config alone cannot tell who gets another value. The
classification is therefore conservative. An edit lowers exposure only when it takes values away and gives nobody
another value. Any other edit that can change who gets which value raises it. A raise that reaches nobody costs
little, because the exposure query measures who gets each value and closes the window. A missed raise lets a bad
rollout through.

Not covered: the holdout, because only experiments write it, and their flags are out of scope. Early access enrollment
and the other super groups, because the early access product owns those flags. The bucketing settings, because they
give people a new draw without a change of the share. A change of `early_exit`.
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
    # The criteria of a condition changed, or the flag-level aggregation changed.
    PROPERTIES_CHANGED = "properties_changed"
    VARIANT_CHANGED = "variant_changed"
    # The conditions have a new order, and the order decides the value of a person who matches two of them.
    CONDITIONS_REORDERED = "conditions_reordered"


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


@frozen
class ExposureChange:
    kinds: frozenset[ExposureChangeKind]
    direction: ExposureDirection
    # The variants that the flag can serve after the edit, from the split and from the variant overrides. A window on
    # a raise tracks the share of people with any value other than false, and the share of each variant. Empty for a
    # boolean flag.
    served_variants: tuple[str, ...]
    # The flag-level group type index after the edit, None for persons. A group flag counts groups, not people.
    aggregation: int | None


@frozen
class _Side:
    split: Split
    conditions: ReleaseConditions
    aggregation: int | None
    early_exit: bool


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


def _served_variants(side: _Side) -> tuple[str, ...]:
    variants = dict.fromkeys(variant.key for variant in served_slots(side.split) if variant.key)
    variants.update(
        dict.fromkeys(condition.variant for condition in side.conditions if condition.rollout > 0 and condition.variant)
    )
    return tuple(variants)


def _serves_anybody(side: _Side) -> bool:
    return any(condition.rollout > 0 for condition in side.conditions)


def _serves_from_split(side: _Side) -> bool:
    return any(condition.rollout > 0 and condition.variant is None for condition in side.conditions)


def _decides(condition: ReleaseCondition, side: _Side) -> bool:
    # With early exit, a person whose properties match a condition and whose hash is outside its rollout gets false,
    # and the flag service reads no later condition for them (`get_match` in rust/feature-flags/src/flags/
    # flag_matching.rs). A condition at 0% then still decides who gets false.
    return condition.rollout > 0 or side.early_exit


# The variant override of a condition, or None with the group type whose key the split hashes.
_Value = tuple[str | None, int | None]


def _value(condition: ReleaseCondition, side: _Side) -> _Value:
    # The split hashes the group key for a group condition and the person for a person condition, so two conditions
    # of different group types give a person different draws of the same split. A boolean flag serves true for both.
    if condition.variant or not served_slots(side.split):
        return (condition.variant, None)
    return (None, condition.aggregation)


def _gives_another_value(released: ReleaseCondition, new: _Side, served_after: set[_Value]) -> bool:
    # A person that a condition no longer serves gets the value of a later condition that matches them, which can
    # differ from the released one. Positions are not compared, so a served condition anywhere in the flag counts,
    # which errs toward a raise.
    return bool(served_after - {_value(released, new)})


def _reordered(pairs: Mapping[int, int]) -> bool:
    order = [pairs[new_index] for new_index in sorted(pairs)]
    return any(earlier > later for earlier, later in zip(order, order[1:]))


def _side(filters: Mapping[str, Any] | None) -> _Side:
    filters = filters or {}
    multivariate = filters.get("multivariate")
    split = parse_variants(multivariate.get("variants") if isinstance(multivariate, Mapping) else None)
    aggregation = filters.get("aggregation_group_type_index")
    aggregation = aggregation if isinstance(aggregation, int) and not isinstance(aggregation, bool) else None
    return _Side(
        split=split,
        conditions=parse_release_conditions(
            filters.get("groups"), flag_aggregation=aggregation, variant_keys=split_variant_keys(split)
        ),
        aggregation=aggregation,
        early_exit=filters.get("early_exit") is True,
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
    if not _decides(previous, old) and not _decides(condition, new):
        return
    if previous.criteria != condition.criteria:
        builder.add(ExposureChangeKind.PROPERTIES_CHANGED)
    if condition.rollout > previous.rollout:
        builder.add(ExposureChangeKind.ROLLOUT_INCREASED)
    elif condition.rollout < previous.rollout:
        # With early exit, the people outside the new rollout get false, not the value of a later condition.
        builder.add(
            ExposureChangeKind.ROLLOUT_DECREASED,
            gives_another_value=not new.early_exit and _gives_another_value(previous, new, served_after),
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
        elif _decides(condition, new):
            builder.add(ExposureChangeKind.CONDITION_ADDED)

    paired_before = set(pairs.values())
    for old_index, removed in enumerate(old.conditions):
        if old_index in paired_before or not _decides(removed, old):
            continue
        # With early exit, the people that the removed condition gave false can get the value of a later condition.
        builder.add(
            ExposureChangeKind.CONDITION_REMOVED,
            gives_another_value=(old.early_exit and removed.rollout < 100)
            or _gives_another_value(removed, new, served_after),
        )

    # A new order gives a person who matches two conditions the value of the one that comes first now. Which pairs
    # of conditions overlap is not known here, so any reorder of conditions with different values counts.
    kept_values = {
        _value(new.conditions[new_index], new) for new_index in pairs if new.conditions[new_index].rollout > 0
    }
    if _reordered(pairs) and (new.early_exit or len(kept_values) > 1):
        builder.add(ExposureChangeKind.CONDITIONS_REORDERED)


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
            builder.add(ExposureChangeKind.ENABLED)
        if before.active and not after.active and _serves_anybody(old):
            builder.add(ExposureChangeKind.DISABLED)
    else:
        if old.aggregation != new.aggregation and _serves_anybody(new):
            builder.add(ExposureChangeKind.PROPERTIES_CHANGED)
        _compare_conditions(old, new, builder)
        if not same_assignment(old.split, new.split) and _serves_from_split(new):
            builder.add(ExposureChangeKind.VARIANT_CHANGED)

    return ExposureChange(
        kinds=builder.kinds(),
        direction=builder.direction(),
        served_variants=_served_variants(new),
        aggregation=new.aggregation,
    )
