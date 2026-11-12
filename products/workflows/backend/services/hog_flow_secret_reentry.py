"""The saves that must carry a workflow step's stored secret inputs typed again.

A function step runs its template's code with its own inputs and mappings, the way a destination runs its code, so a
step follows the destination rule in `products/cdp/backend/secret_reentry.py`. A save that changes a step that holds a
stored secret must carry each of that step's secrets typed again. Secrets are stored by step id, so a save that gives a
step's id to other content changes that step.
"""

import dataclasses
from typing import TYPE_CHECKING, Any, Optional

from posthog.dataclasses import frozen

from products.cdp.backend.secret_reentry import (
    SECRET_REENTRY_COUNTER,
    SECRET_REENTRY_MESSAGE,
    SecretReentry,
    entered_secret_input_keys,
    filled_secret_keys,
    guarded_content,
    secret_reentry_enforced,
    supplied_input_keys,
)
from products.workflows.backend.facade.contracts import WorkflowEditState
from products.workflows.backend.services.hog_flow_secrets import (
    TemplateCache,
    function_template_for_action,
    plaintext_secret_map,
    secret_keys_for_action,
)

if TYPE_CHECKING:
    from posthog.models import Team


@frozen
class TypedSecrets:
    entered: frozenset[str] = frozenset()
    # Keys sent with any value, including a dictionary that still holds some masked entries.
    supplied: frozenset[str] = frozenset()


_NOTHING_TYPED = TypedSecrets()


@frozen
class _SecretSource:
    secrets: dict[str, Any] = dataclasses.field(repr=False)
    steps: dict[str, dict]
    draft: bool


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


def _sources(stored: WorkflowEditState, live_secrets_only: bool, template_cache: TemplateCache) -> list[_SecretSource]:
    # The order validation recovers a secret in, first match winning. `existing_secret_map` merges the same maps in
    # the reverse order, and `live_secret_map` leaves the draft out.
    draft_actions = (stored.draft or {}).get("actions")
    live, draft = _steps(stored.actions), _steps(draft_actions)
    sources = [
        _SecretSource(secrets=stored.draft_encrypted_inputs or {}, steps=draft, draft=True),
        _SecretSource(secrets=stored.encrypted_inputs or {}, steps=live, draft=False),
        _SecretSource(secrets=plaintext_secret_map(draft_actions, template_cache), steps=draft, draft=True),
        _SecretSource(secrets=plaintext_secret_map(stored.actions, template_cache), steps=live, draft=False),
    ]
    return [source for source in sources if not (live_secrets_only and source.draft)]


def _content(step: dict, secret_keys: set[str], template_cache: TemplateCache) -> tuple:
    config = step.get("config") or {}
    template = function_template_for_action(step, template_cache)
    return (
        step.get("type"),
        config.get("template_id"),
        guarded_content(
            None,
            config.get("inputs"),
            template.inputs_schema if template else None,
            config.get("mappings"),
            secret_keys,
        ),
    )


def secrets_to_type_again(
    actions: Any,
    stored: Optional[WorkflowEditState],
    typed: dict[str, TypedSecrets],
    *,
    live_secrets_only: bool,
    template_cache: TemplateCache,
) -> dict[str, list[str]]:
    """The stored secrets each step must carry typed again, by step id. A step is listed when it differs from the
    stored step its secrets are recovered with, or when the request types one of its secrets. Its list is empty when
    the request typed them all."""
    if stored is None:
        return {}
    sources = _sources(stored, live_secrets_only, template_cache)
    result: dict[str, list[str]] = {}
    for step_id, step in _steps(actions).items():
        declared = secret_keys_for_action(step, template_cache)
        held: dict[str, _SecretSource] = {}
        for source in sources:
            for key, entry in (source.secrets.get(step_id) or {}).items():
                if key in declared and isinstance(entry, dict):
                    held.setdefault(key, source)
        filled = filled_secret_keys({key: source.secrets[step_id][key] for key, source in held.items()})
        if not filled:
            continue
        requested = typed.get(step_id, _NOTHING_TYPED)
        changed = False
        for key in filled:
            stored_step = held[key].steps.get(step_id)
            if stored_step is None:
                changed = True
                break
            secret_keys = declared | secret_keys_for_action(stored_step, template_cache)
            if _content(stored_step, secret_keys, template_cache) != _content(step, secret_keys, template_cache):
                changed = True
                break
        # A typed secret is an input change too, because the code can send one secret to an address another holds.
        if changed or requested.supplied & declared:
            result[step_id] = sorted(filled - requested.entered)
    return result


def refused_secret_inputs(
    team: Optional["Team"], to_type_again: dict[str, list[str]], surface: str
) -> Optional[dict[str, dict]]:
    """Count a save that changes a step holding a stored secret. Return the input errors, by step id, when the flag
    is on and the save leaves a secret untyped. A save without a team is counted, never refused."""
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
