"""Bind each secret input of a workflow step to the origins the step's template code can send it to,
with the rules in `products.cdp.backend.secret_binding`.

A save restores a stored secret by step id and key, the staged draft's copy first, so each step is
compared with the step on the side its secret came from. A staged secret without origins was never
checked against its draft step, so it is checked against the live one.
"""

import re
import json
import dataclasses
from collections.abc import Mapping
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.cdp.backend.secret_binding import (
    SecretBinding,
    SecretConfig,
    SecretWrite,
    comparable_inputs,
    entered_secret_input_keys,
    entry_with_origins,
    secret_binding,
    unchanged_secrets,
)
from products.cdp.backend.secret_origins import (
    UNBOUND,
    SecretOrigins,
    mapping_inputs,
    parse_stored_origins,
    secret_origins,
)
from products.workflows.backend.facade.contracts import FlowSecretBinding, WorkflowEditState
from products.workflows.backend.services.hog_flow_secrets import (
    TemplateCache,
    function_template_for_action,
    merge_secret_maps,
    plaintext_secret_map,
    secret_keys_for_action,
)

_NOT_STEP_TEXT = frozenset({"inputs", "mappings"})

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


def _step_text(action: dict, secret_keys: set[str]) -> str:
    # The compiled bytecode stored beside each input names variables too, so only the source is read.
    config = action.get("config") or {}
    inputs = config.get("inputs") or {}
    return json.dumps(
        {
            "type": action.get("type"),
            "output_variable": action.get("output_variable"),
            "config": {key: value for key, value in config.items() if key not in _NOT_STEP_TEXT},
            "inputs": comparable_inputs({key: item for key, item in inputs.items() if key not in secret_keys}),
            "mappings": [comparable_inputs(items) for items in mapping_inputs(config.get("mappings"))],
        },
        sort_keys=True,
        default=str,
    )


def _read_variables(action: dict, template_cache: TemplateCache) -> Optional[set[str]]:
    # A secret input can hold its own address, so its text counts as a read too.
    return _referenced_variables([_template_code(action, template_cache), _step_text(action, set())])


def _writes_any(action: dict, names: Optional[set[str]]) -> bool:
    output_variable = action.get("output_variable")
    entries = output_variable if isinstance(output_variable, list) else [output_variable]
    for entry in entries:
        key = entry.get("key") if isinstance(entry, dict) else None
        if not key:
            continue
        # A spread output writes one variable per property of the result, each named `<key>_<property>`.
        spread = isinstance(entry, dict) and entry.get("spread")
        if names is None or key in names or (spread and any(n.startswith(f"{key}_") for n in names)):
            return True
    return False


def _variable_sources(
    step_id: str, steps: dict[str, dict], template_cache: TemplateCache
) -> tuple[Optional[set[str]], dict[str, dict]]:
    """The variables a step's run can depend on, or None for any, and the steps that write them. A
    step that writes one of them can read other variables to do it, so those count too."""
    names = _read_variables(steps[step_id], template_cache)
    writers: dict[str, dict] = {}
    found = True
    while found:
        found = False
        for writer_id, writer in steps.items():
            if writer_id in writers or not _writes_any(writer, names):
                continue
            writers[writer_id] = writer
            found = True
            writer_names = _read_variables(writer, template_cache)
            names = None if names is None or writer_names is None else names | writer_names
    return names, writers


def _variable_context(step_id: str, steps: dict[str, dict], variables: Any, template_cache: TemplateCache) -> tuple:
    names, writers = _variable_sources(step_id, steps, template_cache)
    return (
        _variable_defaults(variables, names),
        sorted(
            (writer_id, _step_text(writer, secret_keys_for_action(writer, template_cache)))
            for writer_id, writer in writers.items()
        ),
    )


def _variable_defaults(variables: Any, names: Optional[set[str]]) -> dict[Any, Optional[str]]:
    # The API stores every default as text, so a re-save compares equal to a row written another way.
    return {
        item.get("key"): _text(item.get("default"))
        for item in variables or []
        if isinstance(item, dict) and (names is None or item.get("key") in names)
    }


def _secret_config(
    action: dict, inputs: dict, steps: dict[str, dict], variables: Any, template_cache: TemplateCache
) -> SecretConfig:
    return SecretConfig(
        code=_template_code(action, template_cache),
        inputs=inputs,
        mappings=(action.get("config") or {}).get("mappings"),
        context=_variable_context(str(action["id"]), steps, variables, template_cache),
    )


def _unchanged(
    config: SecretConfig, step_id: str, key: str, derived: SecretOrigins, side: _Side, template_cache: TemplateCache
) -> bool:
    stored_action = side.actions.get(step_id)
    if stored_action is None:
        return False
    stored_inputs = {
        **((stored_action.get("config") or {}).get("inputs") or {}),
        **(side.secrets.get(step_id) or {}),
    }
    stored = _secret_config(stored_action, stored_inputs, side.actions, side.variables, template_cache)
    secret_keys = secret_keys_for_action(stored_action, template_cache)
    return key in unchanged_secrets(config, stored, secret_keys, {key: derived})


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
    template_cache: TemplateCache,
) -> FlowSecretBinding:
    """Set `allowed_origins` on every secret input of `actions`, which carry their secrets restored.
    `variables` is None when the save keeps the stored ones. `writes_draft` is true only when the save
    stages a draft: publish and a test run of the draft send what they check, like a live save."""
    secret_steps = _secret_steps(actions, template_cache)
    if not secret_steps:
        return FlowSecretBinding(refused={}, outcomes=[], rewrites_secrets=False)
    stored_secrets = _StoredSecrets(stored, live_secrets_only, template_cache) if stored is not None else None
    if variables is None and stored is not None:
        variables = _draft_variables(stored) if writes_draft else stored.variables
    steps = _steps(actions)
    write = SecretWrite.STAGED_UNBOUND if writes_draft else SecretWrite.LIVE

    refused: dict[str, list[str]] = {}
    outcomes: list[str] = []
    rewrites_secrets = False
    for action, keys in secret_steps:
        config = action["config"]
        inputs = config["inputs"]
        step_id = str(action["id"])
        new_config = _secret_config(action, inputs, steps, variables, template_cache)
        derived = secret_origins(new_config.code, inputs, mapping_inputs(new_config.mappings), keys)
        for key in sorted(keys):
            recovered = stored_secrets.recover(step_id, key) if stored_secrets is not None else None
            is_entered = key in entered.get(step_id, set())
            baseline: Optional[SecretOrigins] = None
            unchanged = False
            if recovered is not None and not is_entered:
                unchanged = _unchanged(new_config, step_id, key, derived[key], recovered.side, template_cache)
                baseline = _baseline(key, step_id, recovered, unchanged, template_cache)
                baseline = derived[key] if baseline is None else baseline
            origins, outcome = secret_binding(derived[key], baseline, is_entered, unchanged)
            entry = entry_with_origins(inputs[key], origins, outcome, derived[key], write)
            rewrites_secrets = rewrites_secrets or entry != inputs[key]
            inputs[key] = entry
            outcomes.append(outcome)
            if outcome == SecretBinding.REFUSED:
                refused.setdefault(step_id, []).append(key)
    return FlowSecretBinding(refused=refused, outcomes=outcomes, rewrites_secrets=rewrites_secrets)


def secrets_sent_by_supplied_variables(
    actions: list[dict],
    *,
    supplied: Mapping[str, Any],
    variables: Any,
    entered: dict[str, set[str]],
    template_cache: TemplateCache,
) -> FlowSecretBinding:
    """The secrets that a test run supplying `supplied` as variable values could send to an address the
    stored origins never named, each refused. Only a secret that may go to any origin can follow a
    variable, and a value equal to its variable's default changes nothing."""
    defaults = _variable_defaults(variables, None)
    changed = {name for name, value in supplied.items() if _text(value) != defaults.get(name)}
    if not changed:
        return FlowSecretBinding(refused={}, outcomes=[], rewrites_secrets=False)
    steps = _steps(actions)
    steered: dict[str, list[str]] = {}
    for action, keys in _secret_steps(actions, template_cache):
        config = action["config"]
        step_id = str(action["id"])
        unbound = [
            key
            for key, origins in secret_origins(
                _template_code(action, template_cache), config["inputs"], mapping_inputs(config.get("mappings")), keys
            ).items()
            if origins is UNBOUND and key not in entered.get(step_id, set())
        ]
        if not unbound:
            continue
        names, _ = _variable_sources(step_id, steps, template_cache)
        if names is None or names & changed:
            steered[step_id] = sorted(unbound)
    outcomes = [str(SecretBinding.REFUSED) for keys in steered.values() for _ in keys]
    return FlowSecretBinding(refused=steered, outcomes=outcomes, rewrites_secrets=False)
