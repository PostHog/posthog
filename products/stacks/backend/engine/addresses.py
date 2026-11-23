import re

from .mappings import SIMPLE_KEY, load_mapping, mappings

LAYOUT = "posthog_dashboard_layout"
EVENT_LINK = "posthog_event_schema"


def address(kind: str, key: str, *, layout: bool = False) -> str:
    resource_type = LAYOUT if layout else load_mapping(kind)["resource_type"]
    label = f"stack_{key}" if SIMPLE_KEY.fullmatch(key) else "encoded_" + key.encode().hex()
    return f"{resource_type}.{label}"


def event_link_address(event_key: str, group_key: str, *, literal: bool = False) -> str:
    prefix = "linkid" if literal else "link"
    return f"{EVENT_LINK}.{prefix}_{event_key.encode().hex()}_{group_key.encode().hex()}"


def _link_keys(value: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"posthog_event_schema\.link(?:id)?_([0-9a-f]+)_([0-9a-f]+)", value)
    if match:
        try:
            return bytes.fromhex(match[1]).decode(), bytes.fromhex(match[2]).decode()
        except ValueError:
            pass
    return None


def event_group_key(value: str) -> str | None:
    keys = _link_keys(value)
    return keys[1] if keys else None


def decode_address(value: str) -> tuple[str, str, bool] | None:
    resource_type, _, label = value.partition(".")
    if resource_type == EVENT_LINK:
        keys = _link_keys(value)
        return ("event", keys[0], True) if keys else None
    if label.startswith("stack_") and SIMPLE_KEY.fullmatch(label[6:]):
        key = label[6:]
    elif label.startswith("encoded_"):
        try:
            key = bytes.fromhex(label[8:]).decode()
        except ValueError:
            return None
    else:
        return None
    if resource_type == LAYOUT:
        return "dashboard", key, True
    for kind, mapping in mappings().items():
        if mapping["resource_type"] == resource_type:
            return kind, key, False
    return None
