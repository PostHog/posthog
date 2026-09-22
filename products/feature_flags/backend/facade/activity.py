import sys
import copy
from collections.abc import Mapping
from typing import Any

from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityContextBase, Change, ChangeAction

from products.feature_flags.backend.facade.config import detect_config_format


def is_v1_config(config: object) -> bool:
    return (config is None or isinstance(config, Mapping)) and detect_config_format(config).kind == "v1"


def is_supported_v2_config(config: object) -> bool:
    if not isinstance(config, Mapping) or detect_config_format(config).kind != "v2":
        return False

    # Validation is only needed for v2 rows; keep its dependencies off the signal startup path.
    from products.feature_flags.backend.facade.config_validation import (  # noqa: PLC0415
        ConfigValidationError,
        ValidationLimits,
        validate_config,
    )

    try:
        validate_config(config, limits=ValidationLimits(max_config_bytes=sys.maxsize, max_metadata_bytes=sys.maxsize))
    except ConfigValidationError:
        return False
    return True


def json_equal(left: object, right: object) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(json_equal(value, right[key]) for key, value in left.items())
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


def _field_changes(before: Mapping[str, Any], after: Mapping[str, Any], prefix: str) -> list[Change]:
    changes = []
    for key in sorted(before.keys() | after.keys()):
        action: ChangeAction
        if key not in before:
            action = "created"
        elif key not in after:
            action = "deleted"
        elif not json_equal(before[key], after[key]):
            action = "changed"
        else:
            continue
        changes.append(Change(type="FeatureFlag", field=f"{prefix}{key}", action=action))
    return changes


@frozen(slots=False)
class FeatureFlagConfigContext(ActivityContextBase):
    filters_version: int = 2
    config_changes: tuple[Change, ...] = ()


def config_change_context(before: object, after: object) -> FeatureFlagConfigContext | None:
    if not is_supported_v2_config(after) or (before is not None and not is_supported_v2_config(before)):
        return None
    assert isinstance(after, Mapping)
    previous = before if isinstance(before, Mapping) else {}
    changes = _field_changes(
        {key: value for key, value in previous.items() if key != "rules"},
        {key: value for key, value in after.items() if key != "rules"},
        "",
    )
    before_rules = {rule["id"]: rule for rule in previous.get("rules", [])}
    after_rules = {rule["id"]: rule for rule in after["rules"]}
    for rule_id in sorted(before_rules.keys() | after_rules.keys()):
        if rule_id not in before_rules:
            changes.append(Change(type="FeatureFlag", field=f"rules/{rule_id}", action="created"))
        elif rule_id not in after_rules:
            changes.append(Change(type="FeatureFlag", field=f"rules/{rule_id}", action="deleted"))
        else:
            changes.extend(_field_changes(before_rules[rule_id], after_rules[rule_id], f"rules/{rule_id}/"))
    if list(before_rules) != list(after_rules):
        changes.append(
            Change(
                type="FeatureFlag",
                field="rule_order",
                action="changed",
                before=list(before_rules),
                after=list(after_rules),
            )
        )
    return FeatureFlagConfigContext(config_changes=tuple(changes))


def activity_event_data(data: dict[str, Any]) -> dict[str, Any]:
    """Keep assignment identity and opaque config values out of destination events."""
    detail = data.get("detail") or {}
    changes = detail.get("changes") or []
    if not any(
        change.get("field") == "filters" and any(not is_v1_config(change.get(side)) for side in ("before", "after"))
        for change in changes
    ):
        return data
    result = copy.deepcopy(data)
    for change in result["detail"]["changes"]:
        if change.get("field") == "filters":
            change["before"] = "masked"
            change["after"] = "masked"
    return result
