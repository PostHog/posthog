from collections.abc import Iterable
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen

from products.workflows.backend.facade.contracts import FlowUtmUpdate, TeamUtmDefaults
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule
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


def flow_ids_with_active_schedule(team_id: int) -> set[UUID]:
    # next_run_at can be empty while the scheduler recalculates it, so an active schedule is enough.
    return set(
        HogFlowSchedule.objects.filter(team_id=team_id, status=HogFlowSchedule.Status.ACTIVE).values_list(
            "hog_flow_id", flat=True
        )
    )


def flow_has_active_schedule(team_id: int, hog_flow_id: UUID) -> bool:
    return HogFlowSchedule.objects.filter(
        team_id=team_id, hog_flow_id=hog_flow_id, status=HogFlowSchedule.Status.ACTIVE
    ).exists()


def is_apply_eligible(flow: HogFlow, has_active_schedule: bool) -> bool:
    if flow.status == HogFlow.State.ARCHIVED:
        return False
    # A broadcast that already went out keeps the links it was sent with.
    return not (
        flow.origin_product == HogFlow.OriginProduct.BROADCASTS
        and flow.status != HogFlow.State.DRAFT
        and not has_active_schedule
    )


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
        # Values the caller supplied for this email are its own, so only the keys it left out follow the default.
        # A new step without a marker would otherwise count as following every default on the next bulk apply.
        # An empty value is a choice too: it asks for the built-in tag, such as the workflow name for utm_campaign.
        raw = config.get("utm_params")
        supplied = {key: raw[key] for key in UTM_KEYS if isinstance(raw, dict) and isinstance(raw.get(key), str)}
        config.setdefault(UTM_FROM_DEFAULT_KEY, [key for key in UTM_KEYS if key not in supplied])
        if "utm_tags_enabled" in config:
            continue
        config["utm_tags_enabled"] = defaults.enabled
        config["utm_params"] = {
            **{key: value for key, value in defaults.params.items() if key not in supplied},
            **supplied,
        }


def _keys_following_default(marker: Any) -> list[str]:
    # Steps saved before the team defaults existed carry no marker. None of them had custom values when
    # the defaults shipped, so every key counts as following the default.
    return [key for key in marker if key in UTM_KEYS] if isinstance(marker, list) else list(UTM_KEYS)


def release_edited_keys(
    actions: list[dict[str, Any]],
    stored_actions: list[Any],
    stored_draft: dict[str, Any] | None,
    defaults: TeamUtmDefaults,
    *,
    saving_draft: bool,
) -> None:
    """Stops a key from following the team default when an edit changes its value, like the email editor does."""
    draft_actions = stored_draft.get("actions") if isinstance(stored_draft, dict) else None
    live = {str(a["id"]): a["config"] for a in stored_actions if is_email_action(a) and a.get("id")}
    draft = {
        str(a["id"]): a["config"]
        for a in (draft_actions if isinstance(draft_actions, list) else [])
        if is_email_action(a) and a.get("id")
    }

    for action in actions:
        if not is_email_action(action):
            continue
        action_id = str(action.get("id"))
        # A draft save edits the staged draft, so its values are the ones the edit started from.
        baseline = (draft.get(action_id) if saving_draft else None) or live.get(action_id) or draft.get(action_id)
        if baseline is None:
            continue
        config = action["config"]
        # A client that resends the config without the marker has not changed which keys follow the default.
        following = _keys_following_default(config.get(UTM_FROM_DEFAULT_KEY, baseline.get(UTM_FROM_DEFAULT_KEY)))
        previous = clean_utm_params(baseline.get("utm_params"))
        current = clean_utm_params(config.get("utm_params"))
        # A value equal to the team default still follows it, so "Save as team default" and the bulk apply keep the key.
        kept = [
            key
            for key in following
            if current.get(key) == defaults.params.get(key) or current.get(key) == previous.get(key)
        ]
        if kept != following or (UTM_FROM_DEFAULT_KEY not in config and UTM_FROM_DEFAULT_KEY in baseline):
            config[UTM_FROM_DEFAULT_KEY] = kept


def apply_defaults_to_email_config(
    config: dict[str, Any], defaults: TeamUtmDefaults, enable_where_off: bool
) -> dict[str, Any] | None:
    """The email step config with the team defaults applied, or None when nothing changes."""
    following = _keys_following_default(config.get(UTM_FROM_DEFAULT_KEY))

    current = clean_utm_params(config.get("utm_params"))
    updated = {key: value for key, value in current.items() if key not in following}
    updated.update({key: value for key, value in defaults.params.items() if key in following})

    enabled = config.get("utm_tags_enabled") is True
    turn_on = enable_where_off and not enabled
    if not enabled and not turn_on:
        return None

    if updated == current and not turn_on:
        return None
    new_config = {**config, "utm_params": updated, UTM_FROM_DEFAULT_KEY: following}
    if turn_on:
        new_config["utm_tags_enabled"] = True
    return new_config


@frozen
class _ActionsUpdate:
    actions: list[dict[str, Any]] | None
    updated_ids: frozenset[str]
    turned_on_ids: frozenset[str]


def _apply_to_actions(actions: list[Any], defaults: TeamUtmDefaults, enable_where_off: bool) -> _ActionsUpdate:
    updated_ids: set[str] = set()
    turned_on_ids: set[str] = set()
    new_actions: list[dict[str, Any]] = []
    for action in actions:
        if not is_email_action(action):
            new_actions.append(action)
            continue
        new_config = apply_defaults_to_email_config(action["config"], defaults, enable_where_off)
        if new_config is None:
            new_actions.append(action)
            continue
        updated_ids.add(str(action.get("id")))
        if new_config.get("utm_tags_enabled") is True and action["config"].get("utm_tags_enabled") is not True:
            turned_on_ids.add(str(action.get("id")))
        new_actions.append({**action, "config": new_config})
    return _ActionsUpdate(
        actions=new_actions if updated_ids else None,
        updated_ids=frozenset(updated_ids),
        turned_on_ids=frozenset(turned_on_ids),
    )


def plan_flow_update(
    actions: list[Any], draft: dict[str, Any] | None, defaults: TeamUtmDefaults, enable_where_off: bool
) -> FlowUtmUpdate | None:
    live = _apply_to_actions(actions, defaults, enable_where_off)
    draft_actions = draft.get("actions") if isinstance(draft, dict) else None
    # A staged draft would undo the change on publish, so it gets the same edit.
    staged = _apply_to_actions(draft_actions, defaults, enable_where_off) if isinstance(draft_actions, list) else None
    if live.actions is None and (staged is None or staged.actions is None):
        return None
    return FlowUtmUpdate(
        actions=live.actions,
        draft_actions=staged.actions if staged else None,
        # The live and staged copies of one email step count once.
        emails_updated=len(live.updated_ids | (staged.updated_ids if staged else frozenset())),
        emails_turned_on=len(live.turned_on_ids | (staged.turned_on_ids if staged else frozenset())),
    )
