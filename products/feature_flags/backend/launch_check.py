from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from posthog.dataclasses import frozen

from products.feature_flags.backend.facade.config import detect_config_format
from products.feature_flags.backend.facade.edits import parse_variants, rolled_out_variant_key, served_slots
from products.feature_flags.backend.facade.filters import condition_aggregation, condition_rollout_percentage


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
        self._side = side
        self._filters: Mapping[str, Any] = side.filters or {}
        groups = self._filters.get("groups")
        self.conditions: Sequence[Mapping[str, Any]] = (
            [condition for condition in groups if isinstance(condition, Mapping)] if isinstance(groups, list) else []
        )
        self.flag_aggregation: int | None = self._filters.get("aggregation_group_type_index")
        self.early_exit = self._filters.get("early_exit") is True
        multivariate = self._filters.get("multivariate")
        self.split = parse_variants(multivariate.get("variants") if isinstance(multivariate, Mapping) else None)

    @property
    def is_on(self) -> bool:
        return self._side.active and not self._side.deleted and not self._side.archived

    @property
    def has_holdout(self) -> bool:
        return bool(self._filters.get("holdout") or self._filters.get("holdout_groups"))

    @property
    def has_enrollment(self) -> bool:
        return bool(self._filters.get("feature_enrollment") or self._filters.get("super_groups"))

    @property
    def runtime_restricted(self) -> bool:
        return self._side.evaluation_runtime not in (None, "all")

    def is_open_to_all(self, condition: Mapping[str, Any]) -> bool:
        return not condition.get("properties") and condition_rollout_percentage(condition) >= 100

    def aggregation(self, condition: Mapping[str, Any]) -> int | None:
        return condition_aggregation(condition, self.flag_aggregation)

    def first_open_condition(self) -> int | None:
        return next((index for index, condition in enumerate(self.conditions) if self.is_open_to_all(condition)), None)

    def gives_false_ahead_of(self, index: int) -> bool:
        aggregation = self.aggregation(self.conditions[index])
        return self.early_exit and any(
            condition_rollout_percentage(condition) < 100
            for condition in self.conditions[:index]
            if self.aggregation(condition) == aggregation
        )

    def reaches_everyone(self) -> bool:
        index = self.first_open_condition()
        return (
            self.is_on
            and index is not None
            and not self.has_holdout
            and not self.has_enrollment
            and not self.runtime_restricted
            and not self.gives_false_ahead_of(index)
        )

    def is_staged(self) -> bool:
        return self.has_enrollment or any(
            condition.get("properties") or condition_rollout_percentage(condition) < 100
            for condition in self.conditions
        )


def _reason(old: _Side, new: _Side, open_index: int) -> LaunchReason | None:
    if new.split:
        return LaunchReason.MULTIVARIATE
    if new.aggregation(new.conditions[open_index]) is not None:
        return LaunchReason.GROUP
    if new.has_holdout:
        return LaunchReason.HOLDOUT
    if new.has_enrollment:
        return LaunchReason.ENROLLMENT
    if new.runtime_restricted:
        return LaunchReason.RUNTIME_RESTRICTED
    if new.gives_false_ahead_of(open_index):
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
    open_index = new.first_open_condition()
    if not new.is_on or open_index is None or old.reaches_everyone():
        return None
    reason = _reason(old, new, open_index)
    return LaunchCheck(qualified=reason is None, reason=reason, release_path=_release_path(old, new))
