"""The saves and runs that must carry a workflow's stored secret inputs typed again.

A function step runs its template's code with its own inputs, the way a destination runs its code, so a workflow
follows the destination rule in `products/cdp/backend/secret_reentry.py`. A step's inputs can read workflow variables,
and other steps, edges and the trigger decide when and with what each step runs. So the rule covers the whole
workflow: a save that changes anything the worker reads must carry every stored secret of the workflow typed again,
and a run that sets its own variables needs the same.
"""

import json
import dataclasses
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Optional

from posthog.dataclasses import frozen

from products.cdp.backend.secret_reentry import (
    SECRET_REENTRY_COUNTER,
    SECRET_REENTRY_MESSAGE,
    SecretReentry,
    authored_inputs,
    authored_mapping,
    entered_secret_input_keys,
    secret_reentry_enforced,
    supplied_input_keys,
    without_derived_fields,
)
from products.workflows.backend.facade.contracts import WorkflowEditState
from products.workflows.backend.services.hog_flow_content import DRAFT_CONTENT_FIELDS
from products.workflows.backend.services.hog_flow_secrets import (
    TemplateCache,
    plaintext_secret_map,
    secret_keys_for_action,
)

if TYPE_CHECKING:
    from posthog.models import Team

# Shown in the editor and in labels, and never read by the code a step runs.
_PRESENTATION_STEP_FIELDS = frozenset({"name", "description", "created_at", "updated_at"})
# Written by the server from the live workflow on every save, whatever the caller sends.
_SERVER_STEP_CONFIG_FIELDS = frozenset({"sensitive"})


@frozen
class TypedSecrets:
    entered: frozenset[str] = frozenset()
    # Keys sent with any value, including a dictionary that still holds some masked entries.
    supplied: frozenset[str] = frozenset()


_NOTHING_TYPED = TypedSecrets()


@frozen
class _SecretSource:
    secrets: dict[str, Any] = dataclasses.field(repr=False)
    content: Mapping[str, Any] = dataclasses.field(repr=False)


def typed_secrets(actions: Any) -> dict[str, TypedSecrets]:
    """What each step's request inputs type. Read it before validation, which recovers stored secrets into them."""
    typed: dict[str, TypedSecrets] = {}
    for step in actions if isinstance(actions, list) else []:
        config = step.get("config") if isinstance(step, dict) else None
        if isinstance(config, dict) and step.get("id"):
            inputs = config.get("inputs")
            typed[str(step["id"])] = TypedSecrets(
                entered=frozenset(entered_secret_input_keys(inputs)),
                supplied=frozenset(supplied_input_keys(inputs)),
            )
    return typed


def _steps(actions: Any) -> dict[str, dict]:
    if not isinstance(actions, list):
        return {}
    return {str(step["id"]): step for step in actions if isinstance(step, dict) and step.get("id")}


def live_workflow_content(stored: WorkflowEditState) -> dict[str, Any]:
    return {field: getattr(stored, field) for field in DRAFT_CONTENT_FIELDS}


def draft_workflow_content(stored: WorkflowEditState) -> dict[str, Any]:
    # A draft written before a content field existed lacks it, and publish keeps the live value for it.
    return {
        **live_workflow_content(stored),
        **{k: v for k, v in (stored.draft or {}).items() if k in DRAFT_CONTENT_FIELDS},
    }


def _sources(stored: WorkflowEditState, live_secrets_only: bool, template_cache: TemplateCache) -> list[_SecretSource]:
    # The order validation recovers a secret in, first match winning. `existing_secret_map` merges the same maps in
    # the reverse order, and `live_secret_map` leaves the draft out. Encrypted maps count every key they hold, not only
    # the keys the step's template declares now, so a template swap cannot hide a stored secret from the check.
    live = live_workflow_content(stored)
    sources = [_SecretSource(secrets=stored.encrypted_inputs or {}, content=live)]
    if stored.draft is not None and not live_secrets_only:
        draft = draft_workflow_content(stored)
        sources.insert(0, _SecretSource(secrets=stored.draft_encrypted_inputs or {}, content=draft))
        sources.append(_SecretSource(secrets=plaintext_secret_map(draft.get("actions"), template_cache), content=draft))
    sources.append(_SecretSource(secrets=plaintext_secret_map(stored.actions, template_cache), content=live))
    return sources


def _held_secrets(
    stored: WorkflowEditState, live_secrets_only: bool, template_cache: TemplateCache
) -> dict[tuple[str, str], _SecretSource]:
    held: dict[tuple[str, str], _SecretSource] = {}
    for source in _sources(stored, live_secrets_only, template_cache):
        for step_id, entries in source.secrets.items():
            for key, entry in (entries if isinstance(entries, dict) else {}).items():
                # A blank optional secret holds nothing the code could send.
                if isinstance(entry, dict) and entry.get("value") not in (None, "", {}):
                    held.setdefault((str(step_id), str(key)), source)
    return held


def _authored_config(config: Any, secret_keys: set[str]) -> Any:
    if not isinstance(config, dict):
        return config
    authored = {key: value for key, value in config.items() if key not in _SERVER_STEP_CONFIG_FIELDS}
    if "inputs" in authored:
        authored["inputs"] = authored_inputs(authored["inputs"], secret_keys)
    if isinstance(authored.get("mappings"), list):
        authored["mappings"] = [authored_mapping(mapping) for mapping in authored["mappings"]]
    return authored


def _authored_step(step: Any, secret_keys: set[str]) -> Any:
    if not isinstance(step, dict):
        return step
    authored = {key: value for key, value in step.items() if key not in _PRESENTATION_STEP_FIELDS}
    if "config" in authored:
        authored["config"] = _authored_config(authored["config"], secret_keys)
    return authored


def _canonical_content(content: Mapping[str, Any], secret_keys_by_step: dict[str, set[str]]) -> str:
    """Everything the worker reads when it runs the workflow, as canonical JSON. Secret values and fields the server
    derives are left out, so a resent masked secret or a recompile does not count as a change."""
    # An empty value runs the same whatever its shape: the model's legacy defaults are `{}` or null where the API
    # writes `[]`, so an unchanged save must not count as a change.
    authored = {field: content.get(field) or None for field in DRAFT_CONTENT_FIELDS}
    actions = authored["actions"] if isinstance(authored["actions"], list) else []
    authored["actions"] = [
        _authored_step(step, secret_keys_by_step.get(str(step.get("id")), set()) if isinstance(step, dict) else set())
        for step in actions
    ]
    # `trigger` is a copy of the trigger step's config, secret inputs included.
    trigger_step = next((s for s in actions if isinstance(s, dict) and s.get("type") == "trigger"), None)
    trigger_keys = secret_keys_by_step.get(str(trigger_step.get("id")), set()) if trigger_step else set()
    authored["trigger"] = _authored_config(authored["trigger"], trigger_keys)
    return json.dumps(authored, default=str, sort_keys=True)


def _secret_keys_by_step(
    contents: list[Mapping[str, Any]], held: dict[tuple[str, str], _SecretSource], template_cache: TemplateCache
) -> dict[str, set[str]]:
    keys: dict[str, set[str]] = {}
    for content in contents:
        for step_id, step in _steps(content.get("actions")).items():
            keys.setdefault(step_id, set()).update(secret_keys_for_action(step, template_cache))
    for step_id, key in held:
        keys.setdefault(step_id, set()).add(key)
    return keys


def secrets_to_type_again(
    content: Mapping[str, Any],
    stored: Optional[WorkflowEditState],
    typed: dict[str, TypedSecrets],
    *,
    live_secrets_only: bool,
    template_cache: TemplateCache,
    supplies_variables: bool = False,
) -> dict[str, list[str]]:
    """The stored secrets this save or run must carry typed again, by step id, when the workflow holds one and the
    request changes what the worker reads, sets its own variables, or types a secret. A step's list is empty when the
    request typed all of its secrets. A stored secret whose step no longer exists, or whose step's template no longer
    declares it, is not listed: the save drops it, so nothing can run with it.

    `content` is every content field as the save leaves it, or as the run reads it."""
    if stored is None:
        return {}
    held = _held_secrets(stored, live_secrets_only, template_cache)
    if not held:
        return {}
    new_steps = _steps(content.get("actions"))
    declared = {step_id: secret_keys_for_action(step, template_cache) for step_id, step in new_steps.items()}
    stored_contents = list({id(source.content): source.content for source in held.values()}.values())
    secret_keys = _secret_keys_by_step([content, *stored_contents], held, template_cache)
    new_canonical = _canonical_content(content, secret_keys)
    changed = supplies_variables or any(
        _canonical_content(stored_content, secret_keys) != new_canonical for stored_content in stored_contents
    )
    # A typed secret is an input change too, because the code can send one secret to an address another holds.
    typed_one = any(typed.get(step_id, _NOTHING_TYPED).supplied & keys for step_id, keys in declared.items())
    if not changed and not typed_one:
        return {}
    result: dict[str, list[str]] = {}
    for step_id, key in sorted(held):
        if key in declared.get(step_id, set()):
            missing = result.setdefault(step_id, [])
            if key not in typed.get(step_id, _NOTHING_TYPED).entered:
                missing.append(key)
    return result


def refused_secret_inputs(
    team: Optional["Team"], to_type_again: dict[str, list[str]], surface: str
) -> Optional[dict[str, dict]]:
    """Count a save or run that changes a workflow holding a stored secret. Return the input errors, by step id, when
    the flag is on and the request leaves a secret untyped. A request without a team is counted, never refused."""
    if not to_type_again:
        return None
    missing = {step_id: keys for step_id, keys in to_type_again.items() if keys}
    if not missing:
        outcome = SecretReentry.REENTERED
    elif team is not None and secret_reentry_enforced(team):
        outcome = SecretReentry.REFUSED
    else:
        outcome = SecretReentry.WOULD_REFUSE
    SECRET_REENTRY_COUNTER.labels(outcome=outcome.value, surface=surface).inc()
    if outcome != SecretReentry.REFUSED:
        return None
    return {step_id: {"inputs": dict.fromkeys(keys, SECRET_REENTRY_MESSAGE)} for step_id, keys in missing.items()}


def supplies_variables(overrides: Any, declared: Any) -> bool:
    """Whether a run sets a variable to anything but the workflow's own default. The editor sends every default with
    a run, so a default sent back does not count. Any other shape counts, since it cannot be compared."""
    if not overrides:
        return False
    if not isinstance(overrides, dict):
        return True
    defaults = {
        variable.get("key"): variable.get("default")
        for variable in (declared if isinstance(declared, list) else [])
        if isinstance(variable, dict)
    }
    return any(key not in defaults or defaults[key] != value for key, value in overrides.items())


def drop_client_compiled_fields(config: Any) -> None:
    """Remove the compiled fields a caller sent with inputs that validation did not compile. The worker runs an
    input's bytecode when it has one, and the secret comparison leaves compiled fields out, so a caller's bytecode
    could otherwise send a stored secret anywhere while the input's value looks unchanged. Without it, the worker uses
    the value as written."""
    if not isinstance(config, dict):
        return
    inputs = config.get("inputs")
    if isinstance(inputs, dict):
        config["inputs"] = {key: without_derived_fields(item) for key, item in inputs.items()}
    mappings = config.get("mappings")
    if isinstance(mappings, list):
        config["mappings"] = [
            {
                **mapping,
                **(
                    {"inputs": {k: without_derived_fields(v) for k, v in mapping["inputs"].items()}}
                    if isinstance(mapping.get("inputs"), dict)
                    else {}
                ),
                **({"filters": without_derived_fields(mapping["filters"])} if "filters" in mapping else {}),
            }
            if isinstance(mapping, dict)
            else mapping
            for mapping in mappings
        ]
