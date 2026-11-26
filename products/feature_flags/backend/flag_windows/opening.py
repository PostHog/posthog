"""What an observation window watches: the flag edit that raised exposure, as the window queries read it."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from products.feature_flags.backend.exposure_change import (
    ExposureChange,
    ExposureChangeKind,
    ExposureDirection,
    FlagExposureConfig,
)
from products.feature_flags.backend.facade.edits import (
    ReleaseCondition,
    Split,
    group_type_index,
    moves_people,
    pair_conditions,
    parse_release_conditions,
    parse_variants,
    same_assignment,
    split_variant_keys,
)
from products.feature_flags.backend.flag_windows.query import WatchedCondition, WatchedEdit

# Changes that can move people in every condition, so the window watches the whole flag.
_FLAG_WIDE_KINDS = frozenset(
    {
        ExposureChangeKind.ENABLED,
        ExposureChangeKind.BUCKETING_CHANGED,
        ExposureChangeKind.CONDITIONS_REORDERED,
        ExposureChangeKind.EARLY_EXIT_TURNED_OFF,
    }
)


def watched_edit(
    *, edit_id: str, edited_at: datetime, before: FlagExposureConfig, after: FlagExposureConfig, change: ExposureChange
) -> WatchedEdit:
    """The edit from `before` to `after`, which `change` classifies as a raise."""
    if change.direction != ExposureDirection.RAISES:
        raise ValueError(f"A window watches an edit that raises exposure, got one that {change.direction}")
    filters = after.filters or {}
    return WatchedEdit(
        id=edit_id,
        flag_key=after.key,
        edited_at=edited_at,
        group_type_index=group_type_index(filters.get("aggregation_group_type_index")),
        variants=change.served_variants,
        enables=ExposureChangeKind.ENABLED in change.kinds,
        conditions=() if change.kinds & _FLAG_WIDE_KINDS else _moved_conditions(before, after),
    )


def _moved_conditions(before: FlagExposureConfig, after: FlagExposureConfig) -> tuple[WatchedCondition, ...]:
    """The conditions after the edit whose people the edit can move, or none when it can move people in all of them."""
    old_filters, new_filters = before.filters or {}, after.filters or {}
    old_split, new_split = _split(old_filters), _split(new_filters)
    # A new split moves the people of every condition that serves from it.
    if not same_assignment(old_split, new_split):
        return ()
    aggregation = old_filters.get("aggregation_group_type_index")
    if group_type_index(aggregation) != group_type_index(new_filters.get("aggregation_group_type_index")):
        return ()
    old = _conditions(old_filters, old_split)
    new = _conditions(new_filters, new_split)
    pairs = pair_conditions(old, new)
    groups: Sequence[Mapping[str, Any]] = new_filters.get("groups") or []
    watched = []
    for index, condition in enumerate(new):
        previous = old[pairs[index]] if index in pairs else None
        if not _moves_people_of(previous, condition):
            continue
        watched.append(
            WatchedCondition(
                position=index,
                properties=_properties(groups[index]),
                earlier_at_full_rollout=tuple(
                    _properties(groups[earlier]) for earlier in range(index) if new[earlier].rollout >= 100
                ),
            )
        )
    return tuple(watched)


def _moves_people_of(previous: ReleaseCondition | None, condition: ReleaseCondition) -> bool:
    if condition.rollout <= 0:
        return False
    if previous is None:
        return True
    return (
        condition.rollout > previous.rollout
        or condition.criteria != previous.criteria
        or moves_people(previous, condition)
    )


def _split(filters: Mapping[str, Any]) -> Split:
    multivariate = filters.get("multivariate")
    return parse_variants(multivariate.get("variants") if isinstance(multivariate, Mapping) else None)


def _conditions(filters: Mapping[str, Any], split: Split) -> tuple[ReleaseCondition, ...]:
    return parse_release_conditions(
        filters.get("groups"),
        flag_aggregation=filters.get("aggregation_group_type_index"),
        variant_keys=split_variant_keys(split),
    )


def _properties(group: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    properties = group.get("properties") if isinstance(group, Mapping) else None
    return tuple(properties) if isinstance(properties, list) else ()
