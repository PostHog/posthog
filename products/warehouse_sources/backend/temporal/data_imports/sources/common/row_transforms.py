"""Shared per-item row transforms usable as REST-source `data_map` callables.

Sources supply their own `data_map` transforms, but some transforms recur across
sources. Centralize those here so a source doesn't re-implement the same loop.
"""

from collections.abc import Iterable
from typing import Any


def coerce_fields_to_str(item: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    """Stringify the named fields in place, so a field whose JSON type varies across
    records (int in some, string in others) infers one stable type when the pipeline
    builds Arrow batches. `None` is left as-is to preserve nullability. Mutates and
    returns `item` so it can be used directly as a `data_map`.
    """
    for field in fields:
        value = item.get(field)
        if value is not None:
            item[field] = str(value)
    return item
