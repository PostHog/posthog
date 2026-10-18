"""
Changes of the flag settings besides the split that decide a person's variant draw, read from the flag's activity
log. Pure functions, no I/O.

The flag service hashes the flag key with an identifier: the group key for a flag that aggregates by a group type,
otherwise the device ID or the distinct ID, as `bucketing_identifier` says, and with experience continuity the
person's stored anonymous ID (`hashed_identifier` in rust/feature-flags/src/flags/flag_matching.rs). A change of any
of them gives the people it touches a new draw, so they can get another variant.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from itertools import groupby

from posthog.dataclasses import frozen

from products.experiments.backend.health.context import BucketingChange, BucketingSetting
from products.feature_flags.backend.facade.filters import condition_aggregation


class BucketingChangeShape(StrEnum):
    # pinned: the finding's subcodes. The page sends them as `finding_variant` on the health finding events.
    KEY_CHANGED = "key_changed"
    AGGREGATION_CHANGED = "aggregation_changed"
    BUCKETING_IDENTIFIER_CHANGED = "bucketing_identifier_changed"
    EXPERIENCE_CONTINUITY_CHANGED = "experience_continuity_changed"
    REVERTED = "reverted"


_SHAPES = {
    BucketingSetting.KEY: BucketingChangeShape.KEY_CHANGED,
    BucketingSetting.AGGREGATION: BucketingChangeShape.AGGREGATION_CHANGED,
    BucketingSetting.BUCKETING_IDENTIFIER: BucketingChangeShape.BUCKETING_IDENTIFIER_CHANGED,
    BucketingSetting.EXPERIENCE_CONTINUITY: BucketingChangeShape.EXPERIENCE_CONTINUITY_CHANGED,
}


@frozen
class BucketingNetEffect:
    shape: BucketingChangeShape
    # One change per setting whose value after its last change differs from before its first, at the time of its
    # last change, in the order of BucketingSetting. Empty when every setting was set back.
    net_changes: tuple[BucketingChange, ...]
    # Every setting that changed, also when it was set back, in the order of BucketingSetting.
    changed_settings: tuple[BucketingSetting, ...]
    first: BucketingChange
    last: BucketingChange
    # The saves that changed a setting. One save can change several.
    change_count: int


def bucketing_changes_from_activity(
    *,
    changed_at: datetime,
    feature_flag_id: int,
    before: Mapping[BucketingSetting, object],
    after: Mapping[BucketingSetting, object],
) -> list[BucketingChange]:
    """The bucketing changes in one activity log row of the flag. A setting the row does not change is absent."""
    changes = []
    for setting in BucketingSetting:
        value_before = _normalized(setting, before.get(setting), feature_flag_id)
        value_after = _normalized(setting, after.get(setting), feature_flag_id)
        if value_before != value_after:
            changes.append(
                BucketingChange(changed_at=changed_at, setting=setting, before=value_before, after=value_after)
            )
    return changes


def conditions_follow_flag_aggregation(aggregation: object, conditions: Sequence[object]) -> bool:
    """
    Whether no release condition aggregates by person while the flag-level aggregation names a group type.
    `changes_that_apply` relies on this, because it reads only the flag-level aggregation of each save. The flag
    serializer keeps it true: it sets the flag-level aggregation to null when the conditions mix aggregations.
    """
    flag_aggregation = _group_type_index(aggregation)
    return flag_aggregation is None or all(
        condition_aggregation(condition, flag_aggregation) is not None
        for condition in conditions
        if isinstance(condition, dict)
    )


def changes_that_apply(
    changes: Sequence[BucketingChange],
    *,
    feature_flag_id: int,
    aggregation: object,
    bucketing_identifier: object,
    trust_flag_aggregation: bool,
) -> tuple[BucketingChange, ...]:
    """
    The changes as the flag service reads them, save by save. It hashes the group key for a flag that aggregates by
    a group type, so it does not read the bucketing identifier and persistence there. It hashes the device ID before
    it reads persistence, so it does not read persistence under device ID bucketing either.

    A setting that changes while the flag service does not read it moves nobody at that save. The new value takes
    effect at the save after which the flag service reads the setting again, so the change counts there, from the
    value that the flag service read last.

    `aggregation` and `bucketing_identifier` are the flag's current values. When `trust_flag_aggregation` is false,
    a release condition can aggregate by person under any flag-level aggregation, so the flag-level aggregation does
    not stop the flag service from reading the identifier.
    """
    state: dict[BucketingSetting, str | int | bool | None] = {
        BucketingSetting.AGGREGATION: _normalized(BucketingSetting.AGGREGATION, aggregation, feature_flag_id),
        BucketingSetting.BUCKETING_IDENTIFIER: _normalized(
            BucketingSetting.BUCKETING_IDENTIFIER, bucketing_identifier, feature_flag_id
        ),
    }
    # Each setting holds the `before` of its first change until that change, and its current value without one.
    for change in reversed(changes):
        state[change.setting] = change.before

    def reads(setting: BucketingSetting) -> bool:
        by_person = state[BucketingSetting.AGGREGATION] is None or not trust_flag_aggregation
        match setting:
            case BucketingSetting.BUCKETING_IDENTIFIER:
                return by_person
            case BucketingSetting.EXPERIENCE_CONTINUITY:
                return by_person and state[BucketingSetting.BUCKETING_IDENTIFIER] == "distinct_id"
            case _:
                return True

    last_read = {setting: value for setting, value in state.items() if reads(setting)}
    applied = []
    for changed_at, saved in groupby(changes, key=lambda change: change.changed_at):
        for change in saved:
            state[change.setting] = change.after
        for setting in BucketingSetting:
            if setting not in state or not reads(setting):
                continue
            # A setting that the flag service never read before has no earlier value to count from. The change
            # that made the flag service read it, such as an aggregation change, counts instead.
            if setting in last_read and last_read[setting] != state[setting]:
                applied.append(
                    BucketingChange(
                        changed_at=changed_at, setting=setting, before=last_read[setting], after=state[setting]
                    )
                )
            last_read[setting] = state[setting]
    return tuple(applied)


def bucketing_net_effect(changes: Sequence[BucketingChange]) -> BucketingNetEffect | None:
    if not changes:
        return None
    net_changes = []
    changed_settings = []
    for setting in BucketingSetting:
        of_setting = [change for change in changes if change.setting == setting]
        if not of_setting:
            continue
        changed_settings.append(setting)
        if of_setting[0].before != of_setting[-1].after:
            net_changes.append(
                BucketingChange(
                    changed_at=of_setting[-1].changed_at,
                    setting=setting,
                    before=of_setting[0].before,
                    after=of_setting[-1].after,
                )
            )
    return BucketingNetEffect(
        shape=_SHAPES[net_changes[0].setting] if net_changes else BucketingChangeShape.REVERTED,
        net_changes=tuple(net_changes),
        changed_settings=tuple(changed_settings),
        first=changes[0],
        last=changes[-1],
        change_count=len({change.changed_at for change in changes}),
    )


def describe_bucketing_value(setting: BucketingSetting, value: str | int | bool | None) -> str:
    """The value as the flag page names it."""
    match setting:
        case BucketingSetting.KEY:
            return f'"{value}"' if isinstance(value, str) else "an unreadable key"
        case BucketingSetting.AGGREGATION:
            return "users" if value is None else "groups"
        case BucketingSetting.BUCKETING_IDENTIFIER:
            return "device ID" if value == "device_id" else "user ID"
        case BucketingSetting.EXPERIENCE_CONTINUITY:
            return "on" if value else "off"


def _normalized(setting: BucketingSetting, value: object, feature_flag_id: int) -> str | int | bool | None:
    # Each setting is read the way the flag service reads it, so a save that writes the default explicitly is
    # no change.
    match setting:
        case BucketingSetting.KEY:
            if not isinstance(value, str):
                return None
            # Deleting a flag that an experiment uses appends this suffix to its key (`FeatureFlag.tombstoned_key`),
            # and restoring it removes the suffix again. Neither is a new key.
            tombstone = f":deleted:{feature_flag_id}"
            return value.removesuffix(tombstone)
        case BucketingSetting.AGGREGATION:
            return _group_type_index(value)
        case BucketingSetting.BUCKETING_IDENTIFIER:
            return "device_id" if value == "device_id" else "distinct_id"
        case BucketingSetting.EXPERIENCE_CONTINUITY:
            return value is True


def _group_type_index(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
