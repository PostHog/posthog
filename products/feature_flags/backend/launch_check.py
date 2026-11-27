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
        return bool(self._filters.get("holdout"))

    @property
    def has_enrollment(self) -> bool:
        return bool(self._filters.get("feature_enrollment"))

    @property
    def runtime_restricted(self) -> bool:
        return self._side.evaluation_runtime not in (None, "all")

    def _first_open_condition(self, *, for_persons: bool) -> int | None:
        return next(
            (
                index
                for index, condition in enumerate(self.conditions)
                if not condition.get("properties")
                and condition_rollout_percentage(condition) >= 100
                and (condition_aggregation(condition, self.flag_aggregation) is None) == for_persons
            ),
            None,
        )

    @property
    def person_catch_all(self) -> int | None:
        return self._first_open_condition(for_persons=True)

    @property
    def group_catch_all(self) -> int | None:
        return self._first_open_condition(for_persons=False)

    def _reachable(self, conditions: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        ended_group_types: set[int] = set()
        reachable: list[Mapping[str, Any]] = []
        for condition in conditions:
            group_type = condition_aggregation(condition, self.flag_aggregation)
            if group_type in ended_group_types:
                continue
            reachable.append(condition)
            if not condition.get("properties") and (condition_rollout_percentage(condition) >= 100 or self.early_exit):
                if group_type is None:
                    break
                ended_group_types.add(group_type)
        return reachable

    def gives_false_ahead_of(self, index: int | None) -> bool:
        return (
            index is not None
            and self.early_exit
            and any(
                condition_rollout_percentage(condition) < 100 for condition in self._reachable(self.conditions[:index])
            )
        )

    def reaches_everyone(self) -> bool:
        return (
            self.is_on
            and self.person_catch_all is not None
            and not self.has_holdout
            and not self.has_enrollment
            and not self.runtime_restricted
            and not self.gives_false_ahead_of(self.person_catch_all)
        )

    def openness(self) -> tuple[bool, ...]:
        return (
            self.is_on,
            self.person_catch_all is not None,
            self.group_catch_all is not None,
            not self.has_holdout,
            not self.has_enrollment,
            not self.runtime_restricted,
            not self.gives_false_ahead_of(self.person_catch_all),
            not self.gives_false_ahead_of(self.group_catch_all),
        )

    def is_staged(self) -> bool:
        return self.has_enrollment or any(
            condition.get("properties") or condition_rollout_percentage(condition) < 100
            for condition in self._reachable(self.conditions)
        )


def _is_candidate(old: _Side, new: _Side) -> bool:
    return (
        new.is_on
        and (new.person_catch_all is not None or new.group_catch_all is not None)
        and not old.reaches_everyone()
        and any(opened and not was_open for opened, was_open in zip(new.openness(), old.openness()))
    )


def _reason(old: _Side, new: _Side) -> LaunchReason | None:
    if new.split:
        return LaunchReason.MULTIVARIATE
    if new.person_catch_all is None:
        return LaunchReason.GROUP
    if new.has_holdout:
        return LaunchReason.HOLDOUT
    if new.has_enrollment:
        return LaunchReason.ENROLLMENT
    if new.runtime_restricted:
        return LaunchReason.RUNTIME_RESTRICTED
    if new.gives_false_ahead_of(new.person_catch_all):
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
    if not _is_candidate(old, new):
        return None
    reason = _reason(old, new)
    return LaunchCheck(qualified=reason is None, reason=reason, release_path=_release_path(old, new))
