from collections.abc import Iterable
from typing import Any

from products.workflows.backend.facade.contracts import FlowUtmUpdate, TeamUtmDefaults
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content")
# Lists the utm_params keys that follow the team default. Bulk updates rewrite only these keys, so a
# value someone typed into one email survives a change to the team defaults.
UTM_FROM_DEFAULT_KEY = "utm_params_from_default"


def load_team_utm_defaults(team_id: int) -> TeamUtmDefaults:
    # Read fresh rather than through Team.workflows_config, which is cached per process.
    row = (
        TeamWorkflowsConfig.objects.filter(team_id=team_id).values("email_utm_tags_enabled", "email_utm_params").first()
    )
    if row is None:
        return TeamUtmDefaults(enabled=False, params={})
    return TeamUtmDefaults(enabled=row["email_utm_tags_enabled"], params=clean_utm_params(row["email_utm_params"]))


def clean_utm_params(params: Any) -> dict[str, str]:
    if not isinstance(params, dict):
        return {}
    return {key: value for key in UTM_KEYS if isinstance(value := params.get(key), str) and value.strip()}


def is_email_action(action: Any) -> bool:
    return (
        isinstance(action, dict) and action.get("type") == "function_email" and isinstance(action.get("config"), dict)
    )


def seed_new_email_actions(
    actions: list[dict[str, Any]], existing_action_ids: Iterable[str], defaults: TeamUtmDefaults
) -> None:
    existing = set(existing_action_ids)
    for action in actions:
        if not is_email_action(action) or action.get("id") in existing:
            continue
        config = action["config"]
        if "utm_tags_enabled" in config:
            continue
        config["utm_tags_enabled"] = defaults.enabled
        config["utm_params"] = dict(defaults.params)
        config[UTM_FROM_DEFAULT_KEY] = list(UTM_KEYS)


def apply_defaults_to_email_config(
    config: dict[str, Any], defaults: TeamUtmDefaults, enable_where_off: bool
) -> dict[str, Any] | None:
    """The email step config with the team defaults applied, or None when nothing changes."""
    marker = config.get(UTM_FROM_DEFAULT_KEY)
    # Steps saved before the team defaults existed carry no marker. None of them had custom values when
    # the defaults shipped, so every key counts as following the default.
    following = [key for key in marker if key in UTM_KEYS] if isinstance(marker, list) else list(UTM_KEYS)

    current = clean_utm_params(config.get("utm_params"))
    updated = {key: value for key, value in current.items() if key not in following}
    updated.update({key: value for key, value in defaults.params.items() if key in following})

    enabled = config.get("utm_tags_enabled") is True
    turn_on = enable_where_off and not enabled

    if updated == current and not turn_on:
        return None
    new_config = {**config, "utm_params": updated, UTM_FROM_DEFAULT_KEY: following}
    if turn_on:
        new_config["utm_tags_enabled"] = True
    return new_config


def _apply_to_actions(
    actions: list[Any], defaults: TeamUtmDefaults, enable_where_off: bool
) -> tuple[list[dict[str, Any]] | None, int, int]:
    changed = False
    updated_count = 0
    turned_on = 0
    new_actions: list[dict[str, Any]] = []
    for action in actions:
        if not is_email_action(action):
            new_actions.append(action)
            continue
        new_config = apply_defaults_to_email_config(action["config"], defaults, enable_where_off)
        if new_config is None:
            new_actions.append(action)
            continue
        changed = True
        updated_count += 1
        if new_config.get("utm_tags_enabled") is True and action["config"].get("utm_tags_enabled") is not True:
            turned_on += 1
        new_actions.append({**action, "config": new_config})
    return (new_actions if changed else None), updated_count, turned_on


def plan_flow_update(
    actions: list[Any], draft: dict[str, Any] | None, defaults: TeamUtmDefaults, enable_where_off: bool
) -> FlowUtmUpdate | None:
    new_actions, updated_count, turned_on = _apply_to_actions(actions, defaults, enable_where_off)
    draft_actions = draft.get("actions") if isinstance(draft, dict) else None
    new_draft_actions = None
    if isinstance(draft_actions, list):
        # A staged draft would undo the change on publish, so it gets the same edit.
        new_draft_actions, draft_count, draft_turned_on = _apply_to_actions(draft_actions, defaults, enable_where_off)
        updated_count = max(updated_count, draft_count)
        turned_on = max(turned_on, draft_turned_on)
    if new_actions is None and new_draft_actions is None:
        return None
    return FlowUtmUpdate(
        actions=new_actions,
        draft_actions=new_draft_actions,
        emails_updated=updated_count,
        emails_turned_on=turned_on,
    )
