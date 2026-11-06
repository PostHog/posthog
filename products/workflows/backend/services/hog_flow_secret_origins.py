"""Bind each secret input of a workflow step to the origins the step's template code can send it to.

The rules are the hog function ones in `products.cdp.backend.secret_binding`. A step runs its
template's code with its own inputs, and a save restores a stored secret by step id and key, the
staged draft's copy first. A stored secret keeps its origins only when its step is the step it was
stored with, so the save compares each step with the step on the side the secret came from. A staged
secret without origins was never checked against its draft step, so it is checked against the live one.
"""

import re
import json
import dataclasses
from collections.abc import Callable
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.cdp.backend.secret_binding import (
    SecretBinding,
    comparable_inputs,
    entered_secret_input_keys,
    secret_binding,
)
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

# A reference to a workflow variable by name. Any other use of `variables`, such as an index by a
# computed key, can read every variable.
_VARIABLE_REFERENCE = re.compile(r"\bvariables\b(?:\s*\.\s*(\w+))?")


@frozen
class _Side:
    actions: dict[str, dict]
    variables: Any
    # The secrets the side's steps run with, by step id and key. A draft runs with the live secrets it
    # does not stage.
    secrets: dict[str, dict] = dataclasses.field(repr=False)
    is_draft: bool


@frozen
class _Store:
    secrets: dict[str, Any] = dataclasses.field(repr=False)
    side: _Side


@frozen
class _Recovered:
    side: _Side
    entry: Optional[dict] = dataclasses.field(repr=False)


@frozen
class _Check:
    action: dict = dataclasses.field(repr=False)
    key: str
    derived: SecretOrigins
    origins: SecretOrigins
    outcome: SecretBinding


def _template_code(action: dict, template_cache: TemplateCache) -> str:
    # A step whose template is gone never runs, so it sends nothing.
    template = function_template_for_action(action, template_cache)
    return (template.code or "") if template else ""


def _text(value: Any) -> Optional[str]:
    return None if value is None else str(value)


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


def _entry(secrets: dict[str, Any], step_id: str, key: str) -> Optional[dict]:
    step_secrets = secrets.get(step_id)
    entry = step_secrets.get(key) if isinstance(step_secrets, dict) else None
    return entry if isinstance(entry, dict) else None


class _StoredSecrets:
    def __init__(self, stored: WorkflowEditState, live_secrets_only: bool, template_cache: TemplateCache) -> None:
        draft_actions = _draft_actions(stored)
        live_plaintext = plaintext_secret_map(stored.actions, template_cache)
        draft_plaintext = plaintext_secret_map(draft_actions, template_cache)
        live_secrets = merge_secret_maps(live_plaintext, _secret_map(stored.encrypted_inputs))
        self.live = _Side(
            actions=_steps(stored.actions), variables=stored.variables, secrets=live_secrets, is_draft=False
        )
        self.draft = _Side(
            actions=_steps(draft_actions),
            variables=_draft_variables(stored),
            secrets=merge_secret_maps(
                merge_secret_maps(merge_secret_maps(live_plaintext, draft_plaintext), live_secrets),
                _secret_map(stored.draft_encrypted_inputs),
            ),
            is_draft=True,
        )
        # The order a save recovers a secret in, first match winning, as `existing_secret_map` merges them.
        stores = [
            _Store(secrets=_secret_map(stored.draft_encrypted_inputs), side=self.draft),
            _Store(secrets=_secret_map(stored.encrypted_inputs), side=self.live),
            _Store(secrets=draft_plaintext, side=self.draft),
            _Store(secrets=live_plaintext, side=self.live),
        ]
        self.stores = [store for store in stores if not (store.side.is_draft and live_secrets_only)]

    def recover(self, step_id: str, key: str) -> Optional[_Recovered]:
        for store in self.stores:
            entry = _entry(store.secrets, step_id, key)
            if entry is None:
                continue
            if store.side.is_draft and parse_stored_origins(entry.get("allowed_origins")) is None:
                return _Recovered(side=self.live, entry=_entry(self.live.secrets, step_id, key))
            return _Recovered(side=store.side, entry=entry)
        return None


def _referenced_variables(texts: list[str]) -> Optional[set[str]]:
    """The names of the variables `texts` read, or None when they may read any."""
    names: set[str] = set()
    for text in texts:
        for match in _VARIABLE_REFERENCE.finditer(text):
            if match.group(1) is None:
                return None
            names.add(match.group(1))
    return names


def _variable_defaults(variables: Any, names: Optional[set[str]]) -> dict[Any, Optional[str]]:
    # The API stores every default as text, so a re-save compares equal to a row written another way.
    return {
        item.get("key"): _text(item.get("default"))
        for item in variables or []
        if isinstance(item, dict) and (names is None or item.get("key") in names)
    }


def _comparable(action: dict, inputs: dict, secret_keys: set[str]) -> tuple:
    config = action.get("config") or {}
    return (
        config.get("template_id") or "",
        comparable_inputs({key: item for key, item in inputs.items() if key not in secret_keys}),
        [comparable_inputs(items) for items in mapping_inputs(config.get("mappings"))],
    )


def _unchanged(
    action: dict,
    inputs: dict,
    variables: Any,
    key: str,
    derived: SecretOrigins,
    side: _Side,
    template_cache: TemplateCache,
) -> bool:
    """Whether the step sends the secret `key` where the step on `side` sends it. Secret values are
    left out of the comparison: the secret's own origins already say where it may go, and another
    secret entered again counts only when it moves where this one goes."""
    step_id = str(action["id"])
    stored_action = side.actions.get(step_id)
    if stored_action is None:
        return False
    stored_inputs = {
        **((stored_action.get("config") or {}).get("inputs") or {}),
        **(side.secrets.get(step_id) or {}),
    }
    secret_keys = secret_keys_for_action(action, template_cache)
    compared = _comparable(action, inputs, secret_keys)
    if compared != _comparable(stored_action, stored_inputs, secret_keys):
        return False
    code = _template_code(action, template_cache)
    # The compiled bytecode stored beside each input names variables too, so only the source is read.
    names = _referenced_variables([code, json.dumps(compared, default=str)])
    if _variable_defaults(variables, names) != _variable_defaults(side.variables, names):
        return False

    def comparable(items: dict, secret_key: str) -> Any:
        return comparable_inputs({secret_key: items.get(secret_key)}).get(secret_key)

    moved_siblings = {
        sibling for sibling in secret_keys - {key} if comparable(inputs, sibling) != comparable(stored_inputs, sibling)
    }
    if not moved_siblings:
        return True
    with_stored_siblings = {name: item for name, item in inputs.items() if name not in moved_siblings}
    with_stored_siblings.update({name: stored_inputs[name] for name in moved_siblings if name in stored_inputs})
    config = action.get("config") or {}
    return secret_origins(code, with_stored_siblings, mapping_inputs(config.get("mappings")), {key})[key] == derived


def _baseline(
    key: str, step_id: str, recovered: _Recovered, unchanged: bool, template_cache: TemplateCache
) -> Optional[SecretOrigins]:
    """The origins the stored secret may go to, or None when it was saved before origins were bound
    and its step is unchanged."""
    entry = recovered.entry
    baseline = parse_stored_origins(entry.get("allowed_origins")) if entry is not None else None
    if baseline is not None or unchanged:
        return baseline
    stored_action = recovered.side.actions.get(step_id)
    if stored_action is None:
        return UNBOUND
    stored_config = stored_action.get("config") or {}
    stored_inputs = {**(stored_config.get("inputs") or {}), **(recovered.side.secrets.get(step_id) or {})}
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


def _secret_steps(actions: list[dict], template_cache: TemplateCache) -> list[tuple[dict, set[str]]]:
    steps = []
    for action in actions:
        config = action.get("config") if isinstance(action, dict) else None
        inputs = config.get("inputs") if isinstance(config, dict) else None
        if not isinstance(inputs, dict) or not action.get("id"):
            continue
        keys = {key for key in secret_keys_for_action(action, template_cache) if isinstance(inputs.get(key), dict)}
        if keys:
            steps.append((action, keys))
    return steps


def bind_flow_secret_origins(
    actions: list[dict],
    *,
    stored: Optional[WorkflowEditState],
    variables: Any,
    entered: dict[str, set[str]],
    live_secrets_only: bool,
    writes_draft: bool,
    enforced: Callable[[], bool],
    template_cache: TemplateCache,
) -> FlowSecretBinding:
    """Set `allowed_origins` on every secret input of `actions`, which carry their secrets restored,
    and name the secrets the save refuses. `variables` is None when the save keeps the stored ones.
    `writes_draft` is true only when the save stages a draft: publish and a test run of the draft send
    what they check, like a live save. `enforced` says whether a secret the save would send outside its
    origins fails the save, and runs only when there is one."""
    secret_steps = _secret_steps(actions, template_cache)
    if not secret_steps:
        return FlowSecretBinding(refused={}, outcomes=[])
    stored_secrets = _StoredSecrets(stored, live_secrets_only, template_cache) if stored is not None else None
    if variables is None and stored is not None:
        variables = _draft_variables(stored) if writes_draft else stored.variables

    checks: list[_Check] = []
    for action, keys in secret_steps:
        config = action["config"]
        inputs = config["inputs"]
        step_id = str(action["id"])
        derived = secret_origins(
            _template_code(action, template_cache), inputs, mapping_inputs(config.get("mappings")), keys
        )
        for key in sorted(keys):
            recovered = stored_secrets.recover(step_id, key) if stored_secrets is not None else None
            is_entered = key in entered.get(step_id, set())
            baseline: Optional[SecretOrigins] = None
            unchanged = False
            if recovered is not None and not is_entered:
                unchanged = _unchanged(action, inputs, variables, key, derived[key], recovered.side, template_cache)
                baseline = _baseline(key, step_id, recovered, unchanged, template_cache)
                baseline = derived[key] if baseline is None else baseline
            origins, outcome = secret_binding(derived[key], baseline, is_entered, unchanged)
            checks.append(_Check(action=action, key=key, derived=derived[key], origins=origins, outcome=outcome))

    enforce = any(check.outcome == SecretBinding.REFUSED for check in checks) and enforced()
    refused: dict[str, list[str]] = {}
    outcomes: list[str] = []
    for check in checks:
        entry = {**check.action["config"]["inputs"][check.key]}
        entry.pop("allowed_origins", None)
        outcome = check.outcome
        if outcome == SecretBinding.REFUSED and enforce:
            refused.setdefault(str(check.action["id"]), []).append(check.key)
        elif outcome == SecretBinding.REFUSED:
            outcome = SecretBinding.WOULD_REFUSE
            # The save goes through. A live save stores where the step now sends the secret. A staged
            # secret stores no origins, so publishing it checks it against the live step.
            if not writes_draft:
                entry["allowed_origins"] = stored_origins(check.derived)
        else:
            entry["allowed_origins"] = stored_origins(check.origins)
        check.action["config"]["inputs"][check.key] = entry
        outcomes.append(outcome)
    return FlowSecretBinding(refused=refused, outcomes=outcomes)
