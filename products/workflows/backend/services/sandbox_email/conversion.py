from copy import deepcopy
from typing import Any

from products.workflows.backend.services.sandbox_email.validation import valid_sandbox_action_id

OWN_EMAIL_ACTION_TYPE = "function_email"
SANDBOX_ACTION_TYPE = "email_sandbox"

_CONTENT_KEYS = ("subject", "preheader", "text", "html", "design")
_CATEGORY_KEYS = ("message_category_id", "message_category_type")

SENDER_OVERRIDE = "from.email and from.name"
SEVERAL_SENDERS = "from.integrationIds"
REPLY_TO = "replyTo"
CC_BCC = "cc and bcc"
TRACKING_OFF = "tracking_enabled: false"
UTM_TAGS = "utm_tags_enabled"


def own_only_settings(action: dict[str, Any]) -> list[str]:
    config = _config(action)
    value = _value(_email(config))
    sender = _sender(value)
    settings: list[str] = []
    if sender.get("email") or sender.get("name") or isinstance(value.get("from"), str) and value["from"]:
        settings.append(SENDER_OVERRIDE)
    rotation = sender.get("integrationIds") or []
    if not isinstance(rotation, list) or len(rotation) > 1:
        settings.append(SEVERAL_SENDERS)
    if value.get("replyTo"):
        settings.append(REPLY_TO)
    if value.get("cc") or value.get("bcc"):
        settings.append(CC_BCC)
    if config.get("tracking_enabled") is False:
        settings.append(TRACKING_OFF)
    if config.get("utm_tags_enabled"):
        settings.append(UTM_TAGS)
    return settings


def to_sandbox_action(action: dict[str, Any]) -> dict[str, Any]:
    config = _config(action)
    email = _email(config)
    return {
        **_graph_fields(action),
        "type": SANDBOX_ACTION_TYPE,
        "config": {
            **_category(config),
            "inputs": {"email": {"templating": "liquid", "value": _content(_value(email))}},
        },
    }


def to_own_email_action(action: dict[str, Any], integration_id: int) -> dict[str, Any]:
    config = _config(action)
    email = _email(config)
    return {
        **_graph_fields(action),
        "type": OWN_EMAIL_ACTION_TYPE,
        "config": {
            "template_id": "template-email",
            **_category(config),
            "inputs": {
                "email": {
                    "templating": "liquid",
                    "value": {**_content(_value(email)), "from": {"integrationId": integration_id}},
                }
            },
        },
    }


def written_in_liquid(action: dict[str, Any]) -> bool:
    return _email(_config(action)).get("templating", "hog") == "liquid"


def can_default_to_sandbox(action: dict[str, Any]) -> bool:
    if (
        action.get("type") != OWN_EMAIL_ACTION_TYPE
        or not valid_sandbox_action_id(action.get("id"))
        or not isinstance(action.get("config"), dict)
    ):
        return False
    sender = _sender(_value(_email(_config(action))))
    return not sender.get("integrationId") and not sender.get("integrationIds") and not own_only_settings(action)


def _graph_fields(action: dict[str, Any]) -> dict[str, Any]:
    return deepcopy({key: field for key, field in action.items() if key not in ("type", "config")})


def _config(action: dict[str, Any]) -> dict[str, Any]:
    config = action.get("config")
    return config if isinstance(config, dict) else {}


def _value(email: dict[str, Any]) -> dict[str, Any]:
    value = email.get("value")
    return value if isinstance(value, dict) else {}


def _email(config: dict[str, Any]) -> dict[str, Any]:
    inputs = config.get("inputs")
    email = inputs.get("email") if isinstance(inputs, dict) else None
    return email if isinstance(email, dict) else {}


def _sender(value: dict[str, Any]) -> dict[str, Any]:
    sender = value.get("from")
    return sender if isinstance(sender, dict) else {}


def _category(config: dict[str, Any]) -> dict[str, Any]:
    return {key: config[key] for key in _CATEGORY_KEYS if config.get(key)}


def _content(value: dict[str, Any]) -> dict[str, Any]:
    to = value.get("to")
    recipient: dict[str, Any] = to if isinstance(to, dict) else {}
    content: dict[str, Any] = {
        "to": {
            "email": recipient["email"] if isinstance(recipient.get("email"), str) else "",
            **({"name": recipient["name"]} if recipient.get("name") else {}),
        }
    }
    for key in _CONTENT_KEYS:
        if value.get(key) is not None:
            content[key] = deepcopy(value[key])
    return content
