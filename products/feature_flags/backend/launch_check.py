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
        self.open_audiences = self._open_audiences()

    def _open_audiences(self) -> dict[int | None, bool]:
        blocked_by: dict[int | None, bool] = {}
        ended_group_types: set[int] = set()
        partial_audiences: set[int | None] = set()
        for condition in self.conditions:
            audience = condition_aggregation(condition, self.flag_aggregation)
            if audience in ended_group_types:
                continue
            rollout = condition_rollout_percentage(condition)
            open_to_everyone = not condition.get("properties") and rollout >= 100
            if open_to_everyone and audience not in blocked_by:
                blocked_by[audience] = self.early_exit and (
                    bool(partial_audiences) if audience is None else bool(partial_audiences & {audience, None})
                )
            if rollout < 100:
                partial_audiences.add(audience)
            if not condition.get("properties") and (open_to_everyone or self.early_exit):
                if audience is None:
                    break
                ended_group_types.add(audience)
        return blocked_by

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

    @property
    def conditions_reach_everyone(self) -> bool:
        return self.open_audiences.get(None) is False

    def reaches_everyone(self) -> bool:
        return (
            self.is_on
            and self.conditions_reach_everyone
            and not self.has_holdout
            and not self.has_enrollment
            and not self.runtime_restricted
        )

    def is_staged(self) -> bool:
        return self.has_enrollment or not self.conditions_reach_everyone

    def open_parts(self) -> set[tuple[str, int | None]]:
        parts: set[tuple[str, int | None]] = set()
        for audience, blocked in self.open_audiences.items():
            parts.add(("open", audience))
            if not blocked:
                parts.add(("unblocked", audience))
        for part, is_open in (
            ("on", self.is_on),
            ("no_holdout", not self.has_holdout),
            ("no_enrollment", not self.has_enrollment),
            ("all_runtimes", not self.runtime_restricted),
        ):
            if is_open:
                parts.add((part, None))
        return parts


def _is_candidate(old: _Side, new: _Side) -> bool:
    return (
        new.is_on
        and bool(new.open_audiences)
        and not old.reaches_everyone()
        and bool(new.open_parts() - old.open_parts())
    )


def _reason(old: _Side, new: _Side) -> LaunchReason | None:
    if new.split:
        return LaunchReason.MULTIVARIATE
    if None not in new.open_audiences:
        return LaunchReason.GROUP
    if new.has_holdout:
        return LaunchReason.HOLDOUT
    if new.has_enrollment:
        return LaunchReason.ENROLLMENT
    if new.runtime_restricted:
        return LaunchReason.RUNTIME_RESTRICTED
    if not new.conditions_reach_everyone:
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
