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
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(tags, list):
        return []
    return [tag for tag in tags if isinstance(tag, str)]
