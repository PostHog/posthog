"""Shared helpers that turn a vendor's nested API object into a flat warehouse row.

Each helper returns a new dict and leaves its input unchanged.
`on_clash` decides which value a key keeps when the lifted object and the row have the same key:
"root" keeps the value already in the row, and "nested" lets the lifted value replace it.
"""

import re
from collections.abc import Callable
from typing import Any, Literal

OnClash = Literal["root", "nested"]

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def camel_to_snake(name: str) -> str:
    """`AnomalyStartDate` -> `anomaly_start_date`, `SOARecord` -> `soa_record`, `snake_case` stays."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def _merge(row: dict[str, Any], values: dict[str, Any], on_clash: OnClash) -> None:
    for key, value in values.items():
        if on_clash == "nested" or key not in row:
            row[key] = value


def flatten_jsonapi(
    item: dict[str, Any],
    *,
    relationships_as_ids: bool = True,
    on_clash: OnClash = "root",
) -> dict[str, Any]:
    """Lift a JSON:API resource's `attributes` into the row root.

    The other root keys (`id`, `type`, `links`, `meta`) stay. With `relationships_as_ids`, the
    `relationships` object becomes one `<name>_id` column for each to-one relationship. To-many
    relationships are dropped. Without it, `relationships` stays in the row as it is.
    """
    excluded = {"attributes", "relationships"} if relationships_as_ids else {"attributes"}
    row = {key: value for key, value in item.items() if key not in excluded}

    attributes = item.get("attributes")
    if isinstance(attributes, dict):
        _merge(row, attributes, on_clash)

    relationships = item.get("relationships")
    if relationships_as_ids and isinstance(relationships, dict):
        ids = {}
        for name, relationship in relationships.items():
            data = relationship.get("data") if isinstance(relationship, dict) else None
            if isinstance(data, dict):
                ids[f"{name}_id"] = data.get("id")
        _merge(row, ids, on_clash)
    return row


def lift_nested(row: dict[str, Any], key: str, *, on_clash: OnClash = "root") -> dict[str, Any]:
    """Move the members of the dict at `row[key]` into the row root and drop `key`.

    When `row[key]` is missing or is not a dict, the row comes back unchanged.
    """
    nested = row.get(key)
    if not isinstance(nested, dict):
        return row
    flat = {name: value for name, value in row.items() if name != key}
    _merge(flat, nested, on_clash)
    return flat


def flatten_nested(
    obj: dict[str, Any],
    *,
    prefix: str = "",
    sep: str = "_",
    key_fn: Callable[[str], str] = camel_to_snake,
    keep_raw: frozenset[str] = frozenset(),
    flatten_list_items: bool = False,
) -> dict[str, Any]:
    """Flatten nested dicts into one level, joining the converted key path with `sep`.

    `{"Impact": {"TotalCost": 1}}` becomes `{"impact_total_cost": 1}`. A key in `keep_raw` is matched
    by its original name at every depth, and its value stays whole. Lists stay as they are, unless
    `flatten_list_items` is set: then each dict in a list is flattened with no prefix.
    """
    flattened: dict[str, Any] = {}
    for key, value in obj.items():
        column = f"{prefix}{sep}{key_fn(key)}" if prefix else key_fn(key)
        if key in keep_raw:
            flattened[column] = value
        elif isinstance(value, dict):
            flattened.update(
                flatten_nested(
                    value,
                    prefix=column,
                    sep=sep,
                    key_fn=key_fn,
                    keep_raw=keep_raw,
                    flatten_list_items=flatten_list_items,
                )
            )
        elif flatten_list_items and isinstance(value, list):
            flattened[column] = [
                flatten_nested(item, sep=sep, key_fn=key_fn, keep_raw=keep_raw, flatten_list_items=True)
                if isinstance(item, dict)
                else item
                for item in value
            ]
        else:
            flattened[column] = value
    return flattened
