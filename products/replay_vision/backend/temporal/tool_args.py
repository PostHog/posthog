"""Coercion for tool arguments the model sends.

Shared by every lookup tool, so hardening the rules once applies to all of them rather than to
whichever tool was edited.
"""

from typing import Any


def parse_seconds(value: Any) -> int | None:
    """Coerce a model-sent tool argument to whole seconds; `None` when it isn't numeric."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            return int(value)
        if isinstance(value, str):
            return int(float(value.strip()))
    except (ValueError, OverflowError):
        return None
    return None
