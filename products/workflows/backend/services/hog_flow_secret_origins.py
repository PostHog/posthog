"""Bind each secret input of a workflow step to the origins the step's template code can send it to.

The rules are the hog function ones in `products.cdp.backend.secret_binding`. A step runs its
template's code with its own inputs, and a save restores a stored secret by step id and key. Each
secret keeps the origins stored with it, and its step is compared with the step the save replaces:
the staged draft step for a draft write, the live step for every write that changes what runs.
"""

import dataclasses
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.cdp.backend.secret_binding import comparable_inputs, entered_secret_input_keys, secret_binding
from products.cdp.backend.secret_origins import (
    UNBOUND,
    SecretOrigins,
    mapping_inputs,
    parse_stored_origins,
    secret_origins,
    stored_origins,
)
from products.workflows.backend.facade.contracts import FlowSecretBinding, WorkflowEditState
from products.workflows.backend.services.hog_flow_secrets import (
    TemplateCache,
    function_template_for_action,
    merge_secret_maps,
    plaintext_secret_map,
    secret_keys_for_action,
)


@frozen
class _StoredSide:
    secrets: dict[str, Any] = dataclasses.field(repr=False)
    actions: dict[str, dict]
    variables: Any


def _template_code(action: dict, template_cache: TemplateCache) -> str:
    # A step whose template is gone never runs, so it sends nothing.
    template = function_template_for_action(action, template_cache)
    return (template.code or "") if template else ""


def _text(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _analyzed_config(action: dict, inputs: dict, variables: Any) -> tuple:
    config = action.get("config") or {}
    return (
        config.get("template_id") or "",
        comparable_inputs(inputs),
        [comparable_inputs(items) for items in mapping_inputs(config.get("mappings"))],
        # The API stores every default as text, so a re-save compares equal to a row written another way.
        [(item.get("key"), _text(item.get("default"))) for item in variables or [] if isinstance(item, dict)],
    )


def _steps(actions: Any) -> dict[str, dict]:
    return {
        str(action["id"]): action
        for action in (actions if isinstance(actions, list) else [])
        if isinstance(action, dict) and action.get("id")
    }


def _secret_map(secrets: Any) -> dict[str, Any]:
    return secrets if isinstance(secrets, dict) else {}


def _draft(stored: WorkflowEditState) -> dict:
    return stored.draft if isinstance(stored.draft, dict) else {}


def _draft_actions(stored: WorkflowEditState) -> Any:
    return _draft(stored).get("actions", stored.actions)


def _draft_variables(stored: WorkflowEditState) -> Any:
    return _draft(stored).get("variables", stored.variables)


def _stored_sides(
    stored: WorkflowEditState, live_secrets_only: bool, template_cache: TemplateCache
) -> list[_StoredSide]:
    draft_actions = _draft_actions(stored)
    draft_side = (_steps(draft_actions), _draft_variables(stored))
    live_side = (_steps(stored.actions), stored.variables)
    # The order a save recovers a secret in, first match winning, as `existing_secret_map` merges them.
    sides = [
        (stored.draft_encrypted_inputs, *draft_side, True),
        (stored.encrypted_inputs, *live_side, False),
        (plaintext_secret_map(draft_actions, template_cache), *draft_side, True),
        (plaintext_secret_map(stored.actions, template_cache), *live_side, False),
    ]
    return [
        _StoredSide(secrets=secrets, actions=actions, variables=variables)
        for secrets, actions, variables, is_draft in sides
        if isinstance(secrets, dict) and not (is_draft and live_secrets_only)
    ]


def _replaced_side(stored: WorkflowEditState, writes_draft: bool, template_cache: TemplateCache) -> _StoredSide:
    """The steps, variables and secrets the save replaces. A draft runs with the live secrets it does not
    stage. Every other write changes what runs live, so it is compared with the live steps and secrets
    even when the secret it keeps is a staged one."""
    live_secrets = merge_secret_maps(
        plaintext_secret_map(stored.actions, template_cache), _secret_map(stored.encrypted_inputs)
    )
    if not writes_draft:
        return _StoredSide(secrets=live_secrets, actions=_steps(stored.actions), variables=stored.variables)
    draft_actions = _draft_actions(stored)
    secrets = merge_secret_maps(
        plaintext_secret_map(stored.actions, template_cache), plaintext_secret_map(draft_actions, template_cache)
    )
    secrets = merge_secret_maps(secrets, _secret_map(stored.encrypted_inputs))
    secrets = merge_secret_maps(secrets, _secret_map(stored.draft_encrypted_inputs))
    return _StoredSide(secrets=secrets, actions=_steps(draft_actions), variables=_draft_variables(stored))


def _stored_entry(side: _StoredSide, step_id: str, key: str) -> Optional[dict]:
    step_secrets = side.secrets.get(step_id)
    entry = step_secrets.get(key) if isinstance(step_secrets, dict) else None
    return entry if isinstance(entry, dict) else None


def _unchanged(action: dict, inputs: dict, variables: Any, key: str, replaced: _StoredSide) -> bool:
    step_id = str(action["id"])
    replaced_action = replaced.actions.get(step_id)
    if replaced_action is None:
        return False
    replaced_secrets = replaced.secrets.get(step_id)
    # The secret's own value is left out. A staged secret someone entered again differs from the live
    # one, and the origins it was bound to when entered already say where it may go.
    replaced_inputs = {
        **((replaced_action.get("config") or {}).get("inputs") or {}),
        **(replaced_secrets if isinstance(replaced_secrets, dict) else {}),
        key: inputs[key],
    }
    return _analyzed_config(action, inputs, replaced.variables if variables is None else variables) == (
        _analyzed_config(replaced_action, replaced_inputs, replaced.variables)
    )


def _baseline(
    key: str, step_id: str, side: _StoredSide, unchanged: bool, template_cache: TemplateCache
) -> Optional[SecretOrigins]:
    """The origins the stored secret may go to, or None when it was saved before origins were bound
    and its step is unchanged."""
    stored_secrets = side.secrets[step_id]
    baseline = parse_stored_origins(stored_secrets[key].get("allowed_origins"))
    if baseline is not None or unchanged:
        return baseline
    stored_action = side.actions.get(step_id)
    if stored_action is None:
        return UNBOUND
    stored_config = stored_action.get("config") or {}
    stored_inputs = {**(stored_config.get("inputs") or {}), **stored_secrets}
    code = _template_code(stored_action, template_cache)
    return secret_origins(code, stored_inputs, mapping_inputs(stored_config.get("mappings")), {key})[key]


def entered_secret_keys(sent_actions: Any, written_actions: Any = None) -> dict[str, set[str]]:
    """Secret input keys by step id whose new value the request carries. Pass `written_actions` when the
    request patches stored steps: a patch merges into the stored inputs, which on a row saved before
    encryption still hold secrets in plaintext, so a key counts only when the request sets its whole
    written value."""
    entered = {
        str(action.get("id")): entered_secret_input_keys(action["config"].get("inputs"))
        for action in (sent_actions if isinstance(sent_actions, list) else [])
        if isinstance(action, dict) and isinstance(action.get("config"), dict)
    }
    if written_actions is None:
        return entered
    sent, written = _steps(sent_actions), _steps(written_actions)

    def value(steps: dict[str, dict], step_id: str, key: str) -> Any:
        item = (((steps.get(step_id) or {}).get("config") or {}).get("inputs") or {}).get(key)
        return item.get("value") if isinstance(item, dict) else None

    return {
        step_id: {key for key in keys if value(written, step_id, key) == value(sent, step_id, key)}
        for step_id, keys in entered.items()
    }


def bind_flow_secret_origins(
    actions: list[dict],
    *,
    stored: Optional[WorkflowEditState],
    variables: Any,
    entered: dict[str, set[str]],
    live_secrets_only: bool,
    writes_draft: bool,
    template_cache: TemplateCache,
) -> FlowSecretBinding:
    """Set `allowed_origins` on every secret input of `actions`, which carry their secrets restored,
    and name the secrets the save would send outside their origins. `variables` is None when the
    save keeps the stored ones. `writes_draft` is true only when the save stages a draft: publish and
    a test run of the draft send what they check, like a live save."""
    sides = _stored_sides(stored, live_secrets_only, template_cache) if stored is not None else []
    replaced = _replaced_side(stored, writes_draft, template_cache) if stored is not None else None
    refused: dict[str, list[str]] = {}
    outcomes: list[str] = []
    for action in actions:
        config = action.get("config") if isinstance(action, dict) else None
        inputs = config.get("inputs") if isinstance(config, dict) else None
        if not isinstance(config, dict) or not isinstance(inputs, dict) or not action.get("id"):
            continue
        keys = {key for key in secret_keys_for_action(action, template_cache) if isinstance(inputs.get(key), dict)}
        if not keys:
            continue
        step_id = str(action["id"])
        derived = secret_origins(
            _template_code(action, template_cache), inputs, mapping_inputs(config.get("mappings")), keys
        )
        for key in sorted(keys):
            side = next((side for side in sides if _stored_entry(side, step_id, key) is not None), None)
            baseline: Optional[SecretOrigins] = None
            unchanged = False
            if side is not None and replaced is not None:
                unchanged = _unchanged(action, inputs, variables, key, replaced)
                baseline = _baseline(key, step_id, side, unchanged, template_cache)
                baseline = derived[key] if baseline is None else baseline
            origins, outcome = secret_binding(derived[key], baseline, key in entered.get(step_id, set()), unchanged)
            inputs[key] = {**inputs[key], "allowed_origins": stored_origins(origins)}
            outcomes.append(outcome)
            if outcome == "refused":
                refused.setdefault(step_id, []).append(key)
    return FlowSecretBinding(refused=refused, outcomes=outcomes)
