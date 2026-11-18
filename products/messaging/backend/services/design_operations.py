import uuid
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


def apply_design_operations(design: dict, operations: list[dict]) -> dict:
    """Apply the ordered operations to a copy of `design` and return the new design. Does not mutate the
    input. Raises ValidationError on operations that can't be applied (unknown id, missing target).
    Structural validity of the result is the caller's responsibility (validate_design)."""
    design = deepcopy(design)
    design.setdefault("counters", {})
    counters = design["counters"]

    for op in operations:
        kind = op["op"]

        if kind == "update_content":
            found = _find_content(design, op["id"])
            if found is None:
                _fail(f"update_content: content '{op['id']}' not found")
            _deep_merge(found[0], op["patch"])

        elif kind == "update_column":
            column = _find_column(design, op["id"])
            if column is None:
                _fail(f"update_column: column '{op['id']}' not found")
            _deep_merge(column, op["patch"])

        elif kind == "update_row":
            row = _find_row(design, op["id"])
            if row is None:
                _fail(f"update_row: row '{op['id']}' not found")
            _deep_merge(row, op["patch"])

        elif kind == "update_body":
            _deep_merge(design.setdefault("body", {}), op["patch"])

        elif kind == "add_content":
            column = _find_column(design, op["column_id"])
            if column is None:
                _fail(f"add_content: column '{op['column_id']}' not found")
            new_content = _prepare_content(op["content"], counters)
            _insert(column.setdefault("contents", []), new_content, op.get("index"))

        elif kind == "remove_content":
            found = _find_content(design, op["id"])
            if found is None:
                _fail(f"remove_content: content '{op['id']}' not found")
            content, column = found
            column["contents"] = [c for c in column["contents"] if c.get("id") != op["id"]]

        elif kind == "move_content":
            found = _find_content(design, op["id"])
            if found is None:
                _fail(f"move_content: content '{op['id']}' not found")
            target_column = _find_column(design, op["column_id"])
            if target_column is None:
                _fail(f"move_content: column '{op['column_id']}' not found")
            content, source_column = found
            source_column["contents"] = [c for c in source_column["contents"] if c.get("id") != op["id"]]
            _insert(target_column.setdefault("contents", []), content, op.get("index"))

        elif kind == "add_row":
            new_row = _prepare_row(op["row"], counters)
            _insert(design.setdefault("body", {}).setdefault("rows", []), new_row, op.get("index"))

        elif kind == "remove_row":
            body = design.get("body") or {}
            rows = body.get("rows") or []
            if not any(r.get("id") == op["id"] for r in rows):
                _fail(f"remove_row: row '{op['id']}' not found")
            body["rows"] = [r for r in rows if r.get("id") != op["id"]]

    return design
