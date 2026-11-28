"""The config of each flag of a team over time, rebuilt from the activity log.

An activity log entry keeps the value before and after each field it changes, so the rebuild starts from the flag as
it is now and undoes the entries from the newest to the oldest. Fields that no entry changes keep the value of the
flag row.
"""

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityLog

from products.feature_flags.backend import ownership
from products.feature_flags.backend.exposure_change import ExposureDirection, FlagExposureConfig
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.rollback_reason import RollbackReason

# The activity log fields of a flag save that `FlagExposureConfig` holds, by the name of its field.
_CONFIG_FIELDS = {
    "active": "active",
    "filters": "filters",
    "key": "key",
    "deleted": "deleted",
    "bucketing_identifier": "bucketing_identifier",
    "ensure_experience_continuity": "ensure_experience_continuity",
}
_BOOLEAN_FIELDS = frozenset({"active", "deleted"})


@frozen
class FlagVersion:
    # When the version starts. The first version of a flag created before the history starts begins at None.
    since: datetime | None
    config: FlagExposureConfig | None
    # The activity log entry that made this version, or None for the version before the first entry read.
    activity_log_id: str | None = None
    rollback_reason: RollbackReason | None = None


@frozen
class FlagHistory:
    flag_id: int
    # Oldest first.
    versions: tuple[FlagVersion, ...]
    # The entries whose logged value after the change differs from the rebuilt config. A write that logs no entry,
    # such as a data migration, shows up there, and the edit before it reads that write as its own.
    mismatches: int = 0

    def config_at(self, moment: datetime) -> FlagExposureConfig | None:
        config = None
        for version in self.versions:
            if version.since is not None and version.since > moment:
                break
            config = version.config
        return config


def flag_histories(team_id: int, since: datetime) -> list[FlagHistory]:
    """The history from `since` of each flag of the team that has an activity log entry since then, deleted flags
    included."""
    entries: dict[int, list[ActivityLog]] = {}
    # Bulk writes log several entries with the same time, so the id orders them as the flag's history page does.
    for entry in ActivityLog.objects.filter(team_id=team_id, scope="FeatureFlag", created_at__gte=since).order_by(
        "-created_at", "-id"
    ):
        if entry.item_id and entry.item_id.isdigit():
            entries.setdefault(int(entry.item_id), []).append(entry)
    flags = FeatureFlag.objects_including_soft_deleted.filter(team_id=team_id, id__in=entries)
    return [rebuild_history(flag.id, exposure_config(flag), entries[flag.id]) for flag in flags]


def owned_flag_ids(team_id: int, flag_ids: Iterable[int]) -> frozenset[int]:
    """The flags among `flag_ids` that another product, such as an experiment, owns."""
    return ownership.owned_flag_ids(
        FeatureFlag.objects_including_soft_deleted.filter(team_id=team_id, id__in=list(flag_ids))
    )


def rebuild_history(flag_id: int, current: FlagExposureConfig, newest_first: Iterable[ActivityLog]) -> FlagHistory:
    """The versions of the flag that ends as `current`, from its activity log entries."""
    versions: list[FlagVersion] = []
    config = current
    created = False
    mismatches = 0
    for entry in newest_first:
        detail = entry.detail or {}
        if _logged_after(detail) != {name: getattr(config, name) for name in _logged_after(detail)}:
            mismatches += 1
        versions.append(
            FlagVersion(
                since=entry.created_at,
                config=config,
                activity_log_id=str(entry.id),
                rollback_reason=_rollback_reason(detail),
            )
        )
        if entry.activity == "created":
            created = True
            break
        config = _undo(config, entry.activity, detail)
    versions.append(FlagVersion(since=None, config=None if created else config))
    return FlagHistory(flag_id=flag_id, versions=tuple(reversed(versions)), mismatches=mismatches)


def _logged(detail: Mapping[str, Any], side: str) -> dict[str, Any]:
    """The values of the config fields that the entry changed, on one side of it."""
    values: dict[str, Any] = {}
    changes: Sequence[Mapping[str, Any]] = detail.get("changes") or []
    for change in changes:
        name = _CONFIG_FIELDS.get(change.get("field") or "")
        if name is not None:
            values[name] = bool(change.get(side)) if name in _BOOLEAN_FIELDS else change.get(side)
    return values


def _logged_after(detail: Mapping[str, Any]) -> dict[str, Any]:
    return _logged(detail, "after")


def _undo(config: FlagExposureConfig, activity: str, detail: Mapping[str, Any]) -> FlagExposureConfig:
    """The config before the entry."""
    values = _logged(detail, "before")
    if activity == "deleted":
        values.setdefault("deleted", False)
        # A bulk delete renames a flag that an experiment uses and logs no change, so the entry's name is the key
        # before the delete.
        if isinstance(detail.get("name"), str):
            values.setdefault("key", detail["name"])
    elif activity == "restored":
        values.setdefault("deleted", True)
    return dataclasses.replace(config, **values)


def _rollback_reason(detail: Mapping[str, Any]) -> RollbackReason | None:
    context = detail.get("context")
    if not isinstance(context, Mapping) or context.get("exposure_direction") != ExposureDirection.LOWERS:
        # A client can send a reason with any edit, and only the reason of an edit that lowered exposure answers why
        # the flag was rolled back.
        return None
    reason = context.get("rollback_reason")
    return RollbackReason(reason) if reason in RollbackReason.values else None


def exposure_config(flag: FeatureFlag) -> FlagExposureConfig:
    return FlagExposureConfig(
        active=flag.active,
        deleted=flag.deleted,
        filters=flag.filters,
        key=flag.key,
        bucketing_identifier=flag.bucketing_identifier,
        ensure_experience_continuity=flag.ensure_experience_continuity,
    )
