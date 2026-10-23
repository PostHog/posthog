"""
Changes of the flag settings besides the split that decide a person's variant draw, read from the flag's activity
log. Pure functions, no I/O. The flags facade (`facade/edits.py`) owns how the flag service reads each setting.
"""

from collections.abc import Sequence
from enum import StrEnum

from posthog.dataclasses import frozen

from products.feature_flags.backend.facade.edits import BucketingChange, BucketingSetting


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
