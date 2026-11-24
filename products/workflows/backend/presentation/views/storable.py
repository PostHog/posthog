"""Customer.io content in a form Postgres can store."""

import re
from typing import Any

_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")


# Deeper content is left for the translator, which fails only the automation that holds it.
_MAX_DEPTH = 200


def storable(value: Any, depth: int = 0) -> Any:
    """`value` with U+FFFD, what a browser shows, for each character Postgres refuses. One such character in one email
    would otherwise stop the whole import, with every other automation in it."""
    if isinstance(value, str):
        return _UNSTORABLE.sub("\ufffd", value)
    if depth == _MAX_DEPTH:
        return value
    if isinstance(value, dict):
        return {storable(key): storable(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [storable(item, depth + 1) for item in value]
    return value
