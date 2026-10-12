"""Minimal codec for the devalue serialization format Framer's Server API speaks.

Framer's headless WebSocket channel encodes every message with devalue
(https://github.com/Rich-Harris/devalue): a JSON array whose index 0 is the root value,
where containers hold indexes into the array, special JS values are negative indexes,
and non-JSON types are `["TypeName", ...]` wrappers. Only the subset the Server API
protocol uses is implemented here.
"""

import json
import math
from datetime import datetime
from typing import Any

UNDEFINED = -1
HOLE = -2
NAN = -3
POSITIVE_INFINITY = -4
NEGATIVE_INFINITY = -5
NEGATIVE_ZERO = -6

_SPECIAL_VALUES: dict[int, Any] = {
    UNDEFINED: None,
    HOLE: None,
    NAN: math.nan,
    POSITIVE_INFINITY: math.inf,
    NEGATIVE_INFINITY: -math.inf,
    NEGATIVE_ZERO: -0.0,
}


def parse(text: str) -> Any:
    """Parse a devalue-encoded payload into plain Python values.

    JS -> Python mapping: undefined/null -> None, Date -> datetime, Set -> list,
    Map -> dict, BigInt -> int, RegExp -> its source string, null-prototype objects ->
    dict. Unknown custom wrappers (e.g. Framer's "plugin-marshal") fall back to their
    hydrated payload.
    """
    parsed = json.loads(text)
    if isinstance(parsed, int) and not isinstance(parsed, bool):
        # A bare special, e.g. `-1` for a top-level `undefined`.
        if parsed in _SPECIAL_VALUES:
            return _SPECIAL_VALUES[parsed]
        raise ValueError(f"Invalid devalue payload: {text[:100]}")
    if not isinstance(parsed, list) or len(parsed) == 0:
        raise ValueError(f"Invalid devalue payload: {text[:100]}")
    return _hydrate(parsed, 0, {})


def _hydrate(nodes: list[Any], index: Any, hydrated: dict[int, Any]) -> Any:
    if not isinstance(index, int) or isinstance(index, bool):
        raise ValueError(f"Invalid devalue reference: {index!r}")
    if index < 0:
        if index in _SPECIAL_VALUES:
            return _SPECIAL_VALUES[index]
        raise ValueError(f"Unknown devalue special value: {index}")
    if index in hydrated:
        return hydrated[index]
    if index >= len(nodes):
        raise ValueError(f"Devalue reference out of range: {index}")

    value = nodes[index]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        obj: dict[str, Any] = {}
        hydrated[index] = obj
        for key, ref in value.items():
            obj[key] = _hydrate(nodes, ref, hydrated)
        return obj
    if isinstance(value, list):
        if len(value) > 0 and isinstance(value[0], str):
            result = _hydrate_typed(nodes, value, hydrated)
            hydrated[index] = result
            return result
        items: list[Any] = []
        hydrated[index] = items
        for ref in value:
            items.append(_hydrate(nodes, ref, hydrated))
        return items
    raise ValueError(f"Invalid devalue node: {value!r}")


def _hydrate_typed(nodes: list[Any], value: list[Any], hydrated: dict[int, Any]) -> Any:
    tag = value[0]
    if tag == "Date":
        return _parse_js_date(value[1])
    if tag == "BigInt":
        return int(value[1])
    if tag in ("Object", "RegExp"):
        # Boxed primitives keep their value; a regex degrades to its source string.
        return value[1]
    if tag == "Set":
        return [_hydrate(nodes, ref, hydrated) for ref in value[1:]]
    if tag == "Map":
        entries = value[1:]
        result: dict[Any, Any] = {}
        for key_ref, value_ref in zip(entries[::2], entries[1::2]):
            key = _hydrate(nodes, key_ref, hydrated)
            if not isinstance(key, str):
                key = json.dumps(key, default=str)
            result[key] = _hydrate(nodes, value_ref, hydrated)
        return result
    if tag == "null":
        # Null-prototype object: [tag, key1, ref1, key2, ref2, ...] with literal string keys.
        entries = value[1:]
        return {key: _hydrate(nodes, ref, hydrated) for key, ref in zip(entries[::2], entries[1::2])}
    if len(value) == 2:
        # Unknown custom wrapper (e.g. "plugin-marshal"): fall back to its payload.
        return _hydrate(nodes, value[1], hydrated)
    raise ValueError(f"Unknown devalue type: {tag!r}")


def _parse_js_date(value: Any) -> Any:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return value


def stringify(value: Any) -> str:
    """Encode a plain Python value as a devalue payload.

    Supports what the protocol's client->server messages need: dict/list containers,
    strings, numbers, booleans, datetimes, and None (encoded as JS `undefined`, which
    is what the official SDK sends for absent values).
    """
    nodes: list[Any] = []

    def flatten(current: Any) -> int:
        if current is None:
            return UNDEFINED
        if isinstance(current, float):
            if math.isnan(current):
                return NAN
            if math.isinf(current):
                return POSITIVE_INFINITY if current > 0 else NEGATIVE_INFINITY
        index = len(nodes)
        nodes.append(None)
        if isinstance(current, dict):
            nodes[index] = {str(key): flatten(item) for key, item in current.items()}
        elif isinstance(current, (list, tuple)):
            nodes[index] = [flatten(item) for item in current]
        elif isinstance(current, datetime):
            nodes[index] = ["Date", current.isoformat()]
        elif isinstance(current, (str, bool, int, float)):
            nodes[index] = current
        else:
            raise TypeError(f"Cannot devalue-encode {type(current).__name__}")
        return index

    root = flatten(value)
    if root < 0:
        return json.dumps(root)
    return json.dumps(nodes, separators=(",", ":"))
