"""Checks on a description before anything about it is stored, and redaction of a diff before it is stored."""

from __future__ import annotations

import json
from typing import Any

from .. import engine_adapter
from ..facade.contracts import StackServiceError
from ..facade.enums import StackErrorKind

MAX_RESOURCES = 2000
MAX_DESCRIPTION_BYTES = 5 * 1024 * 1024
MAX_DEPTH = 32
REDACTED = "[redacted]"


def _invalid(code: str, message: str) -> StackServiceError:
    return StackServiceError(StackErrorKind.INVALID, code, message)


def _depth(value: Any) -> int:
    deepest = 0
    pending: list[tuple[Any, int]] = [(value, 1)]
    while pending:
        item, depth = pending.pop()
        deepest = max(deepest, depth)
        if depth > MAX_DEPTH:
            return depth
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return deepest


def check_limits(description: dict) -> None:
    """Bounds and identities, checked before any query or engine call."""
    resources = description.get("resources", [])
    if len(resources) > MAX_RESOURCES:
        raise _invalid("too_many_definitions", f"A stack holds at most {MAX_RESOURCES} definitions. Split it.")
    # Depth first: encoding a deeply nested value recurses.
    if _depth(description) > MAX_DEPTH:
        raise _invalid("definition_too_deep", f"A definition nests deeper than {MAX_DEPTH} levels. Flatten it.")
    size = len(json.dumps(description, separators=(",", ":")).encode())
    if size > MAX_DESCRIPTION_BYTES:
        raise _invalid("definition_too_large", "The stack's definitions are larger than 5 MB. Split the stack.")
    seen: set[tuple[str, str]] = set()
    for resource in resources:
        kind, key = resource["kind"], resource["key"]
        if (kind, key) in seen:
            raise _invalid("duplicate_definition", f"Two definitions use the {kind} key {key}. Give each its own key.")
        seen.add((kind, key))
        if (error := engine_adapter.validate_key(kind, key)) is not None:
            raise _invalid(str(error.get("code", "invalid_key")), str(error.get("message", "")))


def check_description(description: dict, bindings: list[dict]) -> None:
    """The engine's own checks, including that no secret-bearing field holds a literal value."""
    errors = engine_adapter.validate_description(description, bindings)
    if errors:
        if any(error.get("code") == "runner_unavailable" for error in errors):
            raise StackServiceError(StackErrorKind.UNAVAILABLE, "runner_unavailable", errors[0]["message"])
        first = errors[0]
        raise _invalid(str(first.get("code", "invalid_definition")), " ".join(_located(e) for e in errors))


def _located(error: dict) -> str:
    # The answer has room for one message, so each error names its definition there: the engine's messages
    # alone, like "Add the referenced definition", do not say which one to fix.
    where = " ".join(str(error[part]) for part in ("kind", "key", "path") if error.get(part))
    message = str(error.get("message", ""))
    return f"{where}: {message}" if where else message


# Identities, not values: the scrubber leaves them as they are, so an operation keeps its identity.
IDENTITY_FIELDS = frozenset({"action", "kind", "key", "entity_id", "code", "path"})


def _scrub(value: Any, secret_values: set[str]) -> Any:
    if isinstance(value, str):
        return REDACTED if any(secret and secret in value for secret in secret_values) else value
    if isinstance(value, list):
        return [_scrub(item, secret_values) for item in value]
    if isinstance(value, dict):
        return {
            key: item if key in IDENTITY_FIELDS and isinstance(item, str) else _scrub(item, secret_values)
            for key, item in value.items()
        }
    return value


def redact(diff: dict, secret_values: set[str]) -> dict:
    """A diff safe to store: no value of a sensitive field, no secret anywhere, and errors in public shape only."""
    changes = []
    for change in diff.get("changes", []):
        fields = []
        for field in change.get("fields", []):
            sensitive = bool(field.get("sensitive"))
            fields.append(
                {
                    "path": field.get("path", ""),
                    "before": None if sensitive else field.get("before"),
                    "after": None if sensitive else field.get("after"),
                    "sensitive": sensitive,
                }
            )
        changes.append({**change, "fields": fields})
    drift = []
    for entry in diff.get("drift", []):
        fields = []
        for field in entry.get("fields", []):
            sensitive = bool(field.get("sensitive"))
            fields.append(
                {
                    "path": field.get("path", ""),
                    "pushed": None if sensitive else field.get("pushed"),
                    "found": None if sensitive else field.get("found"),
                    "sensitive": sensitive,
                }
            )
        drift.append({**entry, "fields": fields})
    errors = [
        {key: str(error[key]) for key in ("code", "message", "kind", "key", "path") if error.get(key) is not None}
        for error in diff.get("errors", [])
    ]
    safe = {
        "changes": changes,
        "drift": drift,
        "summary": diff.get("summary", {}),
        "errors": errors,
        "warnings": list(diff.get("warnings", [])),
    }
    return _scrub(safe, secret_values)


def without_values(diff: dict | None) -> dict | None:
    """The change list for a reader who may not see field values."""
    if diff is None:
        return None
    hidden = {"before": None, "after": None, "pushed": None, "found": None}
    return {
        **diff,
        "changes": [
            {
                **change,
                "fields": [
                    {**field, **{k: v for k, v in hidden.items() if k in field}} for field in change.get("fields", [])
                ],
            }
            for change in diff.get("changes", [])
        ],
        "drift": [
            {
                **entry,
                "fields": [
                    {**field, **{k: v for k, v in hidden.items() if k in field}} for field in entry.get("fields", [])
                ],
            }
            for entry in diff.get("drift", [])
        ],
    }
