"""Customer.io content in a form Postgres can store."""

import re
from typing import Any

_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")


def storable(value: Any) -> Any:
    """`value` with U+FFFD, what a browser shows, for each character Postgres refuses. One such character in one email
    would otherwise stop the whole import, with every other automation in it."""
    result = _copied(value)
    # A stack rather than recursion, so no nesting the JSON parser took is too deep.
    stack = [result]
    while stack:
        container = stack.pop()
        if isinstance(container, dict):
            keys: list[Any] = list(container)
        elif isinstance(container, list):
            keys = list(range(len(container)))
        else:
            continue
        for key in keys:
            container[key] = _copied(container[key])
            stack.append(container[key])
    return result


def _copied(value: Any) -> Any:
    if isinstance(value, str):
        return _UNSTORABLE.sub("�", value)
    if isinstance(value, dict):
        return {_copied(key): item for key, item in value.items()}
    if isinstance(value, list):
        return list(value)
    return value
