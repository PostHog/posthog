from copy import deepcopy
from typing import Any, Optional

from products.cdp.backend.models.hog_function_template import HogFunctionTemplate

# Function/email/sms steps (and function-shaped triggers) can carry secret inputs - API keys, auth
# headers - declared `secret: true` on their template's inputs_schema. We split those values out of
# the plaintext `actions` blob into the encrypted `encrypted_inputs` column (keyed by action id then
# input key), mirroring HogFunction.encrypted_inputs. The worker re-merges them at execution time.
_FUNCTION_TRIGGER_CONFIG_TYPES = frozenset({"webhook", "manual", "tracking_pixel"})


# A per-call {template_id: template_or_None} memo. Resolving a template is a DB query, and both the
# read (masking) and write (stripping) paths touch every action, so callers pass one of these to
# dedupe lookups - within a flow, and across a whole list page when stashed on the serializer context.
TemplateCache = dict[str, Optional[Any]]


def _function_template_for_action(action: dict, template_cache: Optional[TemplateCache] = None) -> Optional[Any]:
    # A function step, or a trigger whose source is function-shaped, resolves a template whose
    # inputs_schema tells us which inputs are secret. Everything else has no secret inputs.
    config = action.get("config") or {}
    action_type = action.get("type", "") or ""
    is_function = "function" in action_type or (
        action_type == "trigger" and config.get("type") in _FUNCTION_TRIGGER_CONFIG_TYPES
    )
    if not is_function:
        return None
    template_id = config.get("template_id", "") or ""
    if template_cache is None:
        return HogFunctionTemplate.get_template(template_id)
    if template_id not in template_cache:
        template_cache[template_id] = HogFunctionTemplate.get_template(template_id)
    return template_cache[template_id]


def secret_keys_for_action(action: dict, template_cache: Optional[TemplateCache] = None) -> set[str]:
    template = _function_template_for_action(action, template_cache)
    if not template:
        return set()
    return {schema["key"] for schema in (template.inputs_schema or []) if schema.get("secret")}


def partition_flow_secrets(
    actions: list[dict], template_cache: Optional[TemplateCache] = None
) -> tuple[list[dict], dict[str, dict]]:
    """Split secret inputs out of each action's config.inputs.

    Returns (stripped_actions, encrypted_map) where encrypted_map is {action_id: {input_key: value}}.
    The input list is not mutated. The map is rebuilt from scratch each call - never merged onto a
    prior map - so secrets for deleted or renamed actions drop out rather than orphaning.
    """
    stripped: list[dict] = []
    encrypted: dict[str, dict] = {}
    for original in actions:
        action = deepcopy(original)
        secret_keys = secret_keys_for_action(action, template_cache)
        if secret_keys:
            inputs = (action.get("config") or {}).get("inputs")
            if isinstance(inputs, dict):
                moved = {key: inputs.pop(key) for key in list(inputs) if key in secret_keys}
                if moved:
                    encrypted[action["id"]] = moved
        stripped.append(action)
    return stripped, encrypted


def plaintext_secret_map(actions: Any, template_cache: Optional[TemplateCache] = None) -> dict[str, dict]:
    # The secret inputs still sitting in plaintext inside an actions blob, as an {action_id: {key:
    # value}} map. Non-empty only for legacy rows written before encryption shipped - the recovery
    # base that lets a masked re-save migrate their secrets instead of wiping them.
    if not isinstance(actions, list):
        return {}
    return partition_flow_secrets(actions, template_cache)[1]


def merge_secret_maps(base: Optional[dict], overlay: Optional[dict]) -> dict[str, dict]:
    # Per-action, per-key merge of two {action_id: {key: value}} maps; overlay wins on conflicts.
    result: dict[str, dict] = {action_id: dict(values) for action_id, values in (base or {}).items()}
    for action_id, values in (overlay or {}).items():
        result[action_id] = {**result.get(action_id, {}), **values}
    return result


def recover_or_drop_masked_inputs(inputs: Any, secret_keys: set[str], existing: dict) -> None:
    # A lenient (web draft) save keeps the raw inputs when validation fails. A {"secret": true}
    # read-back marker in that raw payload must never persist as a stored value - the worker would
    # treat the marker object as the real input (e.g. compare it against a webhook's auth header and
    # reject every request). Swap it for the stored secret, or drop the key when there is none.
    if not isinstance(inputs, dict):
        return
    for key in secret_keys:
        value = inputs.get(key)
        if isinstance(value, dict) and value.get("secret") and "value" not in value:
            stored = existing.get(key)
            if stored:
                inputs[key] = stored
            else:
                inputs.pop(key, None)


def mask_secret_action_inputs(
    actions: list[dict], secrets_by_action: dict[str, dict], template_cache: Optional[TemplateCache] = None
) -> list[dict]:
    # Replace every set secret input with the {"secret": True} presence marker for read-back. Mutates
    # the given action dicts (must be a copy - callers deepcopy first). A value counts as set if it
    # lives in the encrypted map or, for legacy rows written before the split, still sits in plaintext.
    for flow_action in actions:
        secret_keys = secret_keys_for_action(flow_action, template_cache)
        if not secret_keys:
            continue
        inputs = (flow_action.get("config") or {}).get("inputs")
        if not isinstance(inputs, dict):
            continue
        action_id = flow_action.get("id")
        action_secrets = secrets_by_action.get(action_id, {}) if isinstance(action_id, str) else {}
        for key in secret_keys:
            if action_secrets.get(key) or inputs.get(key):
                inputs[key] = {"secret": True}
    return actions


def mask_derived_trigger(content: dict, template_cache: Optional[TemplateCache] = None) -> None:
    # The `trigger` representation is derived from the trigger action, so once that action's inputs are
    # masked, re-derive `trigger` from it. Keeps a function-shaped trigger's secret from leaking on the
    # separately-serialized trigger field. No-op when there's no trigger action or no `trigger` key.
    actions = content.get("actions")
    if "trigger" not in content or not isinstance(actions, list):
        return
    trigger_action = next(
        (a for a in actions if isinstance(a, dict) and a.get("type") == "trigger"),
        None,
    )
    if trigger_action is not None:
        content["trigger"] = trigger_action.get("config")


def mask_trigger_config(
    actions: Any, trigger: Any, secrets_by_action: dict[str, dict], template_cache: Optional[TemplateCache] = None
) -> Any:
    # Mask the standalone `trigger` field. Both the minimal and (crucially) the summary serializer
    # return `trigger` while the summary omits `actions`, so it can't be re-derived from masked actions
    # there - a function-shaped trigger's secret would otherwise leak on the MCP list endpoint. Mask
    # from the workflow's own trigger action (or the stored trigger config as a fallback for legacy
    # rows whose actions may be empty).
    trigger_action = next(
        (a for a in (actions or []) if isinstance(a, dict) and a.get("type") == "trigger"),
        None,
    )
    trigger_action = (
        deepcopy(trigger_action)
        if trigger_action is not None
        else {"type": "trigger", "config": deepcopy(trigger) if trigger else {}}
    )
    masked = mask_secret_action_inputs([trigger_action], secrets_by_action, template_cache)
    return masked[0].get("config")


def mask_workflow_fields(
    fields: dict[str, Any],
    *,
    live_actions: Any,
    live_trigger: Any,
    encrypted_inputs: Optional[dict],
    draft_encrypted_inputs: Optional[dict],
    template_cache: TemplateCache,
    mask_trigger: bool = True,
) -> None:
    """Replace each set secret input in the `actions`, `trigger` and `draft` entries of `fields` with
    the {"secret": True} presence marker. Rewrites the entries of `fields`, never the values they
    point to, so the stored workflow stays unchanged."""
    live_secrets = encrypted_inputs or {}
    if isinstance(fields.get("actions"), list):
        fields["actions"] = mask_secret_action_inputs(deepcopy(fields["actions"]), live_secrets, template_cache)
    if mask_trigger and "trigger" in fields:
        fields["trigger"] = mask_trigger_config(live_actions, live_trigger, live_secrets, template_cache)
    draft = fields.get("draft")
    if isinstance(draft, dict) and isinstance(draft.get("actions"), list):
        draft = deepcopy(draft)
        draft["actions"] = mask_secret_action_inputs(
            draft["actions"], merge_secret_maps(live_secrets, draft_encrypted_inputs), template_cache
        )
        mask_derived_trigger(draft, template_cache)
        fields["draft"] = draft


def strip_secrets_from_content(content: dict, template_cache: Optional[TemplateCache] = None) -> dict[str, dict]:
    # Move secret inputs out of content["actions"] into an encrypted map, updating content["actions"]
    # (stripped) and the derived content["trigger"] in place. Returns the {action_id: {key: value}} map.
    # Shared by the live write, the draft write, and (map discarded) the snapshot/compare paths.
    actions = content.get("actions")
    if not isinstance(actions, list):
        return {}
    stripped, encrypted = partition_flow_secrets(actions, template_cache)
    content["actions"] = stripped
    if "trigger" in content:
        trigger_action = next((action for action in stripped if action.get("type") == "trigger"), None)
        if trigger_action is not None:
            content["trigger"] = trigger_action.get("config")
    return encrypted


def strip_content_secrets(content: dict, template_cache: Optional[TemplateCache] = None) -> dict:
    # Return a copy of a content snapshot with secret inputs stripped from actions (and the trigger
    # re-derived). Used to snapshot revisions secret-free and to compare two snapshots secret-free, so a
    # resent secret validation recovers into `actions` doesn't read as a content change against the
    # stored (stripped) snapshot and spuriously bump the revision.
    normalized = dict(content)
    strip_secrets_from_content(normalized, template_cache)
    return normalized


def rehydrate_flow_secrets(actions: list[dict], secrets_by_action: dict[str, dict]) -> list[dict]:
    # Fold decrypted secrets back into each action's config.inputs. Used for inline test runs that
    # ship a config to the executor directly, bypassing the worker's manager (which decrypts normally).
    result: list[dict] = []
    for original in actions:
        action = deepcopy(original)
        action_id = action.get("id")
        action_secrets = secrets_by_action.get(action_id) if isinstance(action_id, str) else None
        config = action.get("config")
        if action_secrets and isinstance(config, dict) and isinstance(config.get("inputs"), dict):
            config["inputs"] = {**config["inputs"], **action_secrets}
        result.append(action)
    return result
