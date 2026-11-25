"""Parsing helpers for list query params shared by the experiments and shared metrics endpoints."""

import json
from typing import Any


def parse_tag_names(value: Any) -> list[str]:
    """Parse a tags query param that arrives as a list or a JSON-encoded string.

    Anything that doesn't decode to a list is ignored rather than an error: a scalar like
    ``?tags=5`` or ``?tags="growth"`` decodes fine but isn't a tag list.
    """
    try:
        tags = value if isinstance(value, list) else json.loads(value) if isinstance(value, str) else []
    except (json.JSONDecodeError, TypeError, RecursionError):
        return []
    if not isinstance(tags, list):
        return []
    return [tag for tag in tags if isinstance(tag, str)]


def parse_created_by_ids(value: str | None) -> list[int]:
    """Parse a `created_by_id` query param into user IDs.

    Accepts a single ID, a comma-separated list or a JSON-encoded list, the same forms the experiments list
    takes. Values that aren't IDs are ignored, and a value that looks like a JSON list but doesn't parse
    matches nothing rather than half-applying.
    """
    text = (value or "").strip()
    if not text:
        return []
    items: Any
    if text.startswith("["):
        try:
            items = json.loads(text)
        except (json.JSONDecodeError, RecursionError):
            return []
        if not isinstance(items, list):
            return []
    else:
        items = text.split(",")
    ids: list[int] = []
    for item in items:
        if isinstance(item, bool):
            continue
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids
