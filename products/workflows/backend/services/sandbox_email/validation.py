import re
from typing import Any

from django.conf import settings

from rest_framework.exceptions import ValidationError

from products.cdp.backend.filters import RUNTIME_CONTRACT
from products.cdp.backend.validation import (
    build_html_wrap_design,
    generate_template_bytecode,
    html_wrap_design_needs_refresh,
)
from products.workflows.backend.models.hog_flow.hog_flow import SANDBOX_EMAIL_ACTION_TYPE

_ACTION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

_CONFIG_KEYS = frozenset({"message_category_id", "message_category_type", "inputs"})
_INPUT_KEYS = frozenset({"email"})
_ENVELOPE_KEYS = frozenset({"templating", "value"})
_VALUE_KEYS = frozenset({"to", "subject", "preheader", "text", "html", "design"})
_RECIPIENT_KEYS = frozenset({"email", "name"})
_STRING_VALUE_KEYS = ("subject", "preheader", "text", "html")
_COMPILED_KEYS = ("bytecode", "input_deps", "bytecode_contract")

_CATEGORY_TYPES = ("marketing", "transactional")
_TEMPLATING = ("hog", "liquid")

ADOPTION_UNAVAILABLE = "The sandbox sender isn't available for this organization. Choose a verified email sender."
INVALID_ACTION_ID = "A sandbox email step ID can only use letters, numbers, '-' and '_', up to 128 characters."


def valid_sandbox_action_id(action_id: Any) -> bool:
    return isinstance(action_id, str) and bool(_ACTION_ID.match(action_id))


RUNTIME_UNAVAILABLE = "The sandbox sender can't send from workflows yet. Save this workflow as a draft, or choose a verified email sender."


def require_sandbox_runtime(actions: Any) -> None:
    if settings.WORKFLOWS_SANDBOX_EMAIL_RUNTIME_ENABLED:
        return
    if any(isinstance(action, dict) and action.get("type") == SANDBOX_EMAIL_ACTION_TYPE for action in actions or []):
        raise ValidationError({"actions": RUNTIME_UNAVAILABLE})


def validate_sandbox_email_action(
    action: dict[str, Any],
    *,
    stored_sandbox_action_ids: set[str],
    adoption_enabled: bool,
    require_complete: bool = True,
    is_dwh_source: bool = False,
) -> dict[str, Any]:
    action_id = action.get("id")
    if not valid_sandbox_action_id(action_id):
        raise ValidationError({"id": INVALID_ACTION_ID})
    if action_id not in stored_sandbox_action_ids and not adoption_enabled:
        raise ValidationError({"type": ADOPTION_UNAVAILABLE})

    config = action.get("config")
    if not isinstance(config, dict):
        raise ValidationError({"config": "A sandbox email step needs a config object."})
    _reject_unknown_keys(config, _CONFIG_KEYS)

    category_type = config.get("message_category_type")
    if category_type is not None and category_type not in _CATEGORY_TYPES:
        raise ValidationError({"config": "'message_category_type' must be 'marketing' or 'transactional'."})
    category_id = config.get("message_category_id")
    if category_id is not None and not isinstance(category_id, str):
        raise ValidationError({"config": "'message_category_id' must be a string."})

    inputs = config.get("inputs")
    if not isinstance(inputs, dict) or not isinstance(inputs.get("email"), dict):
        raise ValidationError({"config": "A sandbox email step needs an 'inputs.email' object."})
    _reject_unknown_keys(inputs, _INPUT_KEYS)

    envelope = {key: value for key, value in inputs["email"].items() if key not in _COMPILED_KEYS}
    _reject_unknown_keys(envelope, _ENVELOPE_KEYS)
    templating = envelope.get("templating", "hog")
    if templating not in _TEMPLATING:
        raise ValidationError({"config": "'templating' must be 'hog' or 'liquid'."})

    value = envelope.get("value")
    if not isinstance(value, dict):
        raise ValidationError({"config": "The sandbox email needs a 'value' object."})
    _validate_email_value(value, require_complete=require_complete)
    html = value.get("html")
    if isinstance(html, str) and html and html_wrap_design_needs_refresh(html, value.get("design")):
        value = {**value, "design": build_html_wrap_design(html)}
        envelope["value"] = value

    if templating == "hog":
        envelope.update(_compile(value, is_dwh_source=is_dwh_source))
    inputs["email"] = envelope
    return action


def _reject_unknown_keys(obj: dict[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(key for key in obj if key not in allowed)
    if unknown:
        listed = ", ".join(f"'{key}'" for key in unknown)
        raise ValidationError({"config": f"A sandbox email step can't set {listed}."})


def _validate_email_value(value: dict[str, Any], *, require_complete: bool) -> None:
    _reject_unknown_keys(value, _VALUE_KEYS)

    recipient = value.get("to")
    if recipient is not None:
        if not isinstance(recipient, dict):
            raise ValidationError({"config": "'to' must be an object with 'email' and an optional 'name'."})
        _reject_unknown_keys(recipient, _RECIPIENT_KEYS)
    recipient = recipient or {}

    wrong_types = [
        f"'to.{key}'" for key in ("email", "name") if key in recipient and not isinstance(recipient[key], str)
    ]
    wrong_types += [f"'{key}'" for key in _STRING_VALUE_KEYS if key in value and not isinstance(value[key], str)]
    if wrong_types:
        raise ValidationError({"config": f"Expected text for {', '.join(wrong_types)}."})
    if value.get("design") is not None and not isinstance(value["design"], dict):
        raise ValidationError({"config": "'design' must be an object."})

    if not require_complete:
        return
    missing = [f"'{key}'" for key in ("to.email", "subject") if not _lookup(value, key)]
    if not value.get("text") and not value.get("html"):
        missing.append("either 'text' or 'html'")
    if missing:
        label = "value" if len(missing) == 1 else "values"
        raise ValidationError({"config": f"Missing {label} for {', '.join(missing)}."})


def _lookup(value: dict[str, Any], dotted: str) -> Any:
    found: Any = value
    for part in dotted.split("."):
        found = found.get(part) if isinstance(found, dict) else None
    return found


def _compile(value: dict[str, Any], *, is_dwh_source: bool) -> dict[str, Any]:
    sendable = {key: field for key, field in value.items() if key != "design"}
    input_deps: set[str] = set()
    try:
        bytecode = generate_template_bytecode(
            sendable, input_deps, function_type="destination", is_dwh_source=is_dwh_source
        )
    except Exception as error:
        raise ValidationError({"config": f"Invalid template: {error}"})
    return {"bytecode": bytecode, "input_deps": sorted(input_deps), "bytecode_contract": RUNTIME_CONTRACT}
