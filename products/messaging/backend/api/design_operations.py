import uuid
from collections.abc import Callable
from copy import deepcopy
from typing import Any, NoReturn, Optional

from rest_framework import serializers

# Surgical, id-addressed edits to an Unlayer email design (the content.email.design tree). The caller
# sends a small, ordered list of operations instead of re-transmitting the whole design; these are
# applied to the stored design and the result is validated + re-rendered to HTML by the serializer.
# Pure functions here — no DB, no HTML rendering — so they're cheap to unit-test exhaustively.
#
# The design tree is body.rows[].columns[].contents[]; every row, column, and content item carries a
# stable string `id`, which is how operations address them (indexes shift when blocks are added or
# removed; ids don't). For add_* operations the caller may omit the bookkeeping fields (`id`, and the
# `_meta.htmlID` / `counters` numbering Unlayer tracks per element type) — they're filled in here so a
# caller never has to compute them.


def _deep_merge(target: dict, patch: dict) -> dict:
    """Recursively merge `patch` into `target`. A null leaf deletes the key; a dict merges into a dict;
    anything else replaces. Lets a caller change values.text without resending the rest of values."""
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def _fail(message: str) -> NoReturn:
    raise serializers.ValidationError({"operations": message})


def _new_id() -> str:
    # Unlayer ids are arbitrary unique strings; the editor uses ~10-char tokens. uuid4 keeps collisions
    # astronomically unlikely without needing to scan the existing tree.
    return uuid.uuid4().hex[:10]


def _counter_key(node_kind: str, content_type: Optional[str] = None) -> str:
    # Counter/htmlID prefixes mirror what the Unlayer editor emits: u_row, u_column, u_content_<type>.
    if node_kind == "content":
        return f"u_content_{content_type or 'text'}"
    return f"u_{node_kind}"


def _assign_meta(node: dict, counter_key: str, counters: dict) -> None:
    """Number a freshly added node the way the editor would: bump the per-type counter and stamp the
    matching _meta.htmlID so the rendered HTML ids stay consistent."""
    n = int(counters.get(counter_key, 0)) + 1
    counters[counter_key] = n
    values = node.setdefault("values", {})
    meta = values.setdefault("_meta", {})
    meta["htmlID"] = f"{counter_key}_{n}"
    meta.setdefault("htmlClassNames", counter_key)


def _prepare_content(content: dict, counters: dict) -> dict:
    content = deepcopy(content)
    if not content.get("id"):
        content["id"] = _new_id()
    _assign_meta(content, _counter_key("content", content.get("type")), counters)
    return content


def _prepare_row(row: dict, counters: dict) -> dict:
    row = deepcopy(row)
    if not row.get("id"):
        row["id"] = _new_id()
    _assign_meta(row, _counter_key("row"), counters)
    for column in row.get("columns") or []:
        if not column.get("id"):
            column["id"] = _new_id()
        _assign_meta(column, _counter_key("column"), counters)
        column["contents"] = [_prepare_content(c, counters) for c in column.get("contents") or []]
    return row


def _iter_rows(design: dict) -> list[dict]:
    body = design.get("body") or {}
    return body.get("rows") or []


def _find_content(design: dict, content_id: str) -> Optional[tuple[dict, dict]]:
    """Return (content, containing_column) for the content item with `content_id`, or None."""
    for row in _iter_rows(design):
        for column in row.get("columns") or []:
            for content in column.get("contents") or []:
                if content.get("id") == content_id:
                    return content, column
    return None


def _find_column(design: dict, column_id: str) -> Optional[dict]:
    for row in _iter_rows(design):
        for column in row.get("columns") or []:
            if column.get("id") == column_id:
                return column
    return None


def _find_row(design: dict, row_id: str) -> Optional[dict]:
    for row in _iter_rows(design):
        if row.get("id") == row_id:
            return row
    return None


def _insert(items: list, item: Any, index: Optional[int]) -> None:
    if index is None or index >= len(items):
        items.append(item)
    else:
        items.insert(max(index, 0), item)


def _require_content(design: dict, kind: str, content_id: str) -> tuple[dict, dict]:
    found = _find_content(design, content_id)
    if found is None:
        _fail(f"{kind}: content '{content_id}' not found")
    return found


def _require_row(design: dict, kind: str, row_id: str) -> dict:
    row = _find_row(design, row_id)
    if row is None:
        _fail(f"{kind}: row '{row_id}' not found")
    return row


def _require_column(design: dict, kind: str, column_id: str) -> dict:
    column = _find_column(design, column_id)
    if column is None:
        _fail(f"{kind}: column '{column_id}' not found")
    return column


# One handler per operation kind, all with the same (design, op, counters) signature so `_OPERATIONS`
# can dispatch on `op["op"]` alone. Each handler edits `design` in place; the caller owns the copy.
def _update_content(design: dict, op: dict, counters: dict) -> None:
    content, _ = _require_content(design, "update_content", op["id"])
    _deep_merge(content, op["patch"])


def _update_column(design: dict, op: dict, counters: dict) -> None:
    _deep_merge(_require_column(design, "update_column", op["id"]), op["patch"])


def _update_row(design: dict, op: dict, counters: dict) -> None:
    _deep_merge(_require_row(design, "update_row", op["id"]), op["patch"])


def _update_body(design: dict, op: dict, counters: dict) -> None:
    _deep_merge(design.setdefault("body", {}), op["patch"])


def _add_content(design: dict, op: dict, counters: dict) -> None:
    column = _require_column(design, "add_content", op["column_id"])
    _insert(column.setdefault("contents", []), _prepare_content(op["content"], counters), op.get("index"))


def _remove_content(design: dict, op: dict, counters: dict) -> None:
    _, column = _require_content(design, "remove_content", op["id"])
    column["contents"] = [c for c in column["contents"] if c.get("id") != op["id"]]


def _move_content(design: dict, op: dict, counters: dict) -> None:
    content, source_column = _require_content(design, "move_content", op["id"])
    target_column = _require_column(design, "move_content", op["column_id"])
    source_column["contents"] = [c for c in source_column["contents"] if c.get("id") != op["id"]]
    _insert(target_column.setdefault("contents", []), content, op.get("index"))


def _add_row(design: dict, op: dict, counters: dict) -> None:
    _insert(design.setdefault("body", {}).setdefault("rows", []), _prepare_row(op["row"], counters), op.get("index"))


def _remove_row(design: dict, op: dict, counters: dict) -> None:
    # The row exists, so body and body.rows do too.
    _require_row(design, "remove_row", op["id"])
    body = design["body"]
    body["rows"] = [r for r in body["rows"] if r.get("id") != op["id"]]


_OPERATIONS: dict[str, Callable[[dict, dict, dict], None]] = {
    "update_content": _update_content,
    "update_column": _update_column,
    "update_row": _update_row,
    "update_body": _update_body,
    "add_content": _add_content,
    "remove_content": _remove_content,
    "move_content": _move_content,
    "add_row": _add_row,
    "remove_row": _remove_row,
}


def apply_design_operations(design: dict, operations: list[dict]) -> dict:
    """Apply the ordered operations to a copy of `design` and return the new design. Does not mutate the
    input. Raises ValidationError on operations that can't be applied (unknown id, missing target).
    Structural validity of the result is the caller's responsibility (validate_design)."""
    design = deepcopy(design)
    design.setdefault("counters", {})
    counters = design["counters"]

    for op in operations:
        # Both callers validate `op` against a ChoiceField first, so an unknown kind here is a no-op
        # rather than an error.
        handler = _OPERATIONS.get(op["op"])
        if handler is not None:
            handler(design, op, counters)

    return design
