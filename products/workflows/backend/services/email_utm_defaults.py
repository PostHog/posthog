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
        supplied = clean_utm_params(config.get("utm_params"))
        config.setdefault(UTM_FROM_DEFAULT_KEY, [key for key in UTM_KEYS if key not in supplied])
        if "utm_tags_enabled" in config:
            continue
        config["utm_tags_enabled"] = defaults.enabled
        config["utm_params"] = {
            **{key: value for key, value in defaults.params.items() if key not in supplied},
            **supplied,
        }


def _keys_following_default(config: dict[str, Any]) -> list[str]:
    marker = config.get(UTM_FROM_DEFAULT_KEY)
    # Steps saved before the team defaults existed carry no marker. None of them had custom values when
    # the defaults shipped, so every key counts as following the default.
    return [key for key in marker if key in UTM_KEYS] if isinstance(marker, list) else list(UTM_KEYS)


def release_edited_keys(
    actions: list[dict[str, Any]],
    stored_actions: list[Any],
    stored_draft: dict[str, Any] | None,
    defaults: TeamUtmDefaults,
) -> None:
    """Stops a key from following the team default when an edit changes its value, like the email editor does."""
    draft_actions = stored_draft.get("actions") if isinstance(stored_draft, dict) else None
    stored: dict[str, list[dict[str, str]]] = {}
    for action in [*stored_actions, *(draft_actions if isinstance(draft_actions, list) else [])]:
        if is_email_action(action) and action.get("id"):
            stored.setdefault(str(action["id"]), []).append(clean_utm_params(action["config"].get("utm_params")))

    for action in actions:
        previous = stored.get(str(action.get("id"))) if is_email_action(action) else None
        if not previous:
            continue
        config = action["config"]
        following = _keys_following_default(config)
        current = clean_utm_params(config.get("utm_params"))
        # A value equal to the team default still follows it, so "Save as team default" and the bulk apply keep the key.
        kept = [
            key
            for key in following
            if current.get(key) == defaults.params.get(key)
            or all(params.get(key) == current.get(key) for params in previous)
        ]
        if kept != following:
            config[UTM_FROM_DEFAULT_KEY] = kept
