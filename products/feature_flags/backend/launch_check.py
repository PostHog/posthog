from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from posthog.dataclasses import frozen

from products.feature_flags.backend.facade import filters as flag_filters
from products.feature_flags.backend.facade.config import detect_config_format
from products.feature_flags.backend.facade.edits import parse_variants, rolled_out_variant_key, served_slots


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
        conditions = self.conditions = [c for c in filters.get("groups") or [] if isinstance(c, Mapping)]
        aggregation, early_exit = filters.get("aggregation_group_type_index"), filters.get("early_exit") is True
        rollout = flag_filters.condition_rollout_percentage
        reachable = flag_filters.reachable_conditions(conditions, flag_aggregation=aggregation, early_exit=early_exit)
        self.open = [i for i in reachable if not conditions[i].get("properties") and rollout(conditions[i]) >= 100]
        person = [i for i in self.open if flag_filters.condition_aggregation(conditions[i], aggregation) is None]
        self.catch_all = person[0] if person else None
        partial = [rollout(condition) < 100 for condition in conditions]
        self.blocked = early_exit and any(partial[: self.catch_all or 0])
        restricted = {
            LaunchReason.HOLDOUT: bool(filters.get("holdout")),
            LaunchReason.ENROLLMENT: bool(filters.get("feature_enrollment")),
            LaunchReason.RUNTIME_RESTRICTED: side.evaluation_runtime not in (None, "all"),
        }
        self.restrictions = [reason for reason, present in restricted.items() if present]
        self.staged = restricted[LaunchReason.ENROLLMENT] or (self.catch_all is None and any(partial))
        self.is_on = side.active and not side.deleted and not side.archived
        unblocked = self.catch_all is not None and not self.blocked
        self.reaches_everyone = self.is_on and unblocked and not self.restrictions
        self.reach = (self.is_on, bool(self.open), bool(person), unblocked, *(not p for p in restricted.values()))
        self.split = parse_variants((filters.get("multivariate") or {}).get("variants"))


def _reason(old: _Side, new: _Side) -> LaunchReason | None:
    if new.split:
        return LaunchReason.MULTIVARIATE
    if new.catch_all is None:
        return LaunchReason.GROUP
    if new.restrictions:
        return new.restrictions[0]
    if new.blocked:
        return LaunchReason.EARLY_EXIT
    return None if old.staged else LaunchReason.NOT_STAGED_BEFORE


def _release_path(old: _Side, new: _Side) -> ReleasePath:
    if LaunchReason.ENROLLMENT in old.restrictions and LaunchReason.ENROLLMENT not in new.restrictions:
        return ReleasePath.ENROLLMENT_REMOVED
    if len(served_slots(old.split)) > 1 and rolled_out_variant_key(new.split) is not None:
        return ReleasePath.VARIANT_ROLLOUT
    if not old.is_on and old.conditions == new.conditions:
        return ReleasePath.ENABLED
    return ReleasePath.CONDITIONS


def check_launch(before: FlagLaunchSide, after: FlagLaunchSide) -> LaunchCheck | None:
    if detect_config_format(before.filters).kind != "v1" or detect_config_format(after.filters).kind != "v1":
        return None
    old, new = _Side(before), _Side(after)
    opened = any(now and not was for now, was in zip(new.reach, old.reach))
    if not new.is_on or not new.open or old.reaches_everyone or not opened:
        return None
    reason = _reason(old, new)
    return LaunchCheck(qualified=reason is None, reason=reason, release_path=_release_path(old, new))
