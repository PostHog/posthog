"""Helpers for incident tables that keep their text in nested JSON (updates, comments, entities)."""

import json
from typing import Any

from products.signals.backend.emission._common import parse_json_list

MAX_UPDATE_CHARS = 1000
MAX_LIST_ITEMS = 20


def parse_json_object(raw: Any) -> dict[str, Any]:
    """Warehouse object columns arrive as either a native dict or a JSON-encoded string."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def latest_text(
    items: list[Any],
    *,
    text_keys: tuple[str, ...],
    time_keys: tuple[str, ...] = (),
    newest_first: bool = False,
) -> str:
    """Text of the newest entry that has any.

    Entries are ordered by the first time key any of them carries, as long as every value present
    for it has one type (ISO strings and epoch numbers both sort correctly within one source).
    Entries missing that key count as the oldest. When no entry has a time key, the list order decides.
    """
    candidates = [(item, _first_text(item, text_keys)) for item in items if isinstance(item, dict)]
    candidates = [(item, text) for item, text in candidates if text]
    if not candidates:
        return ""
    for key in time_keys:
        stamped: list[tuple[Any, str]] = [
            (item.get(key), text) for item, text in candidates if item.get(key) is not None
        ]
        if not stamped:
            continue
        stamps = [stamp for stamp, _ in stamped]
        if all(isinstance(stamp, str) for stamp in stamps) or all(
            isinstance(stamp, int | float) and not isinstance(stamp, bool) for stamp in stamps
        ):
            return max(stamped, key=lambda pair: pair[0])[1][:MAX_UPDATE_CHARS]
    ordered = candidates if newest_first else candidates[::-1]
    return ordered[0][1][:MAX_UPDATE_CHARS]


def names_from_list(raw: Any, name_keys: tuple[str, ...] = ("name",)) -> list[str]:
    """Names from a list of strings or objects; empty and duplicate names are dropped."""
    names: list[str] = []
    for item in parse_json_list(raw):
        name = item.strip() if isinstance(item, str) else _first_text(item, name_keys) if isinstance(item, dict) else ""
        if name and name not in names:
            names.append(name)
        if len(names) >= MAX_LIST_ITEMS:
            break
    return names


def str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def page_scoped_id(page_id: Any, item_id: Any) -> str:
    """Status page children are keyed by `(page_id, id)` in the warehouse, so the id alone can collide across pages."""
    return f"{page_id}:{item_id}" if page_id else str(item_id)
