from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from posthog.dataclasses import frozen

from products.feature_flags.backend.facade.config import detect_config_format
from products.feature_flags.backend.facade.edits import parse_variants, rolled_out_variant_key, served_slots
from products.feature_flags.backend.facade.filters import (
    condition_aggregation,
    condition_rollout_percentage,
    reachable_conditions,
)


class LaunchReason(StrEnum):
    MULTIVARIATE = "multivariate"
    GROUP = "group"
    HOLDOUT = "holdout"
    ENROLLMENT = "enrollment"
    RUNTIME_RESTRICTED = "runtime_restricted"
    EARLY_EXIT = "early_exit"
    NOT_STAGED_BEFORE = "not_staged_before"


class ReleasePath(StrEnum):
    CONDITIONS = "conditions"
    ENABLED = "enabled"
    ENROLLMENT_REMOVED = "enrollment_removed"
    VARIANT_ROLLOUT = "variant_rollout"


@frozen
class FlagLaunchSide:
    active: bool
    deleted: bool
    archived: bool
    filters: Mapping[str, Any] | None
    evaluation_runtime: str | None


@frozen
class LaunchCheck:
    qualified: bool
    reason: LaunchReason | None
    release_path: ReleasePath


class _Side:
    def __init__(self, side: FlagLaunchSide) -> None:
        filters: Mapping[str, Any] = side.filters or {}
        groups = filters.get("groups")
        self.conditions: Sequence[Mapping[str, Any]] = (
            [condition for condition in groups if isinstance(condition, Mapping)] if isinstance(groups, list) else []
        )
        aggregation = filters.get("aggregation_group_type_index")
        early_exit = filters.get("early_exit") is True
        self.reachable = reachable_conditions(self.conditions, flag_aggregation=aggregation, early_exit=early_exit)
        self.open = [
            index
            for index in self.reachable
            if not self.conditions[index].get("properties")
            and condition_rollout_percentage(self.conditions[index]) >= 100
        ]
        self.catch_all = next(
            (index for index in self.open if condition_aggregation(self.conditions[index], aggregation) is None), None
        )
        ahead = range(self.catch_all or 0)
        self.blocked_strictly = early_exit and any(
            condition_rollout_percentage(self.conditions[index]) < 100 for index in ahead
        )
        self.blocked_leniently = early_exit and any(
            condition_rollout_percentage(self.conditions[index]) < 100 for index in self.reachable if index in ahead
        )
        self.is_on = side.active and not side.deleted and not side.archived
        self.has_holdout = bool(filters.get("holdout"))
        self.has_enrollment = bool(filters.get("feature_enrollment"))
        self.runtime_restricted = side.evaluation_runtime not in (None, "all")
        multivariate = filters.get("multivariate")
        self.split = parse_variants(multivariate.get("variants") if isinstance(multivariate, Mapping) else None)

    def conditions_reach_everyone(self, *, strictly: bool) -> bool:
        blocked = self.blocked_strictly if strictly else self.blocked_leniently
        return self.catch_all is not None and not blocked

    def reaches_everyone(self) -> bool:
        return (
            self.is_on
            and self.conditions_reach_everyone(strictly=False)
            and not (self.has_holdout or self.has_enrollment or self.runtime_restricted)
        )

    def is_staged(self) -> bool:
        return self.has_enrollment or (bool(self.conditions) and not self.conditions_reach_everyone(strictly=False))

    def reach_parts(self) -> tuple[bool, ...]:
        return (
            self.is_on,
            self.catch_all is not None,
            len(self.open) > (self.catch_all is not None),
            self.conditions_reach_everyone(strictly=True),
            not self.has_holdout,
            not self.has_enrollment,
            not self.runtime_restricted,
        )


def _reason(old: _Side, new: _Side) -> LaunchReason | None:
    if new.split:
        return LaunchReason.MULTIVARIATE
    if new.catch_all is None:
        return LaunchReason.GROUP
    if new.has_holdout:
        return LaunchReason.HOLDOUT
    if new.has_enrollment:
        return LaunchReason.ENROLLMENT
    if new.runtime_restricted:
        return LaunchReason.RUNTIME_RESTRICTED
    if not new.conditions_reach_everyone(strictly=True):
        return LaunchReason.EARLY_EXIT
    if not old.is_staged():
        return LaunchReason.NOT_STAGED_BEFORE
    return None


def _release_path(old: _Side, new: _Side) -> ReleasePath:
    if old.has_enrollment and not new.has_enrollment:
        return ReleasePath.ENROLLMENT_REMOVED
    if len(served_slots(old.split)) > 1 and rolled_out_variant_key(new.split) is not None:
        return ReleasePath.VARIANT_ROLLOUT
    if not old.is_on and old.conditions == new.conditions:
        return ReleasePath.ENABLED
    return ReleasePath.CONDITIONS


def check_launch(before: FlagLaunchSide, after: FlagLaunchSide) -> LaunchCheck | None:
    if detect_config_format(before.filters).kind != "v1" or detect_config_format(after.filters).kind != "v1":
        return None
    old = _Side(before)
    new = _Side(after)
    opened = any(now and not was for now, was in zip(new.reach_parts(), old.reach_parts()))
    if not new.is_on or not new.open or old.reaches_everyone() or not opened:
        return None
    reason = _reason(old, new)
    return LaunchCheck(qualified=reason is None, reason=reason, release_path=_release_path(old, new))
