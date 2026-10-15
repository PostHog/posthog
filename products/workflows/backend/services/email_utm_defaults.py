from collections.abc import Iterable
from typing import Any

from products.workflows.backend.facade.contracts import TeamUtmDefaults
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content")
# Lists the utm_params keys that follow the team default, so a value someone typed into one email
# stays apart from a copied default when the team defaults change.
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
