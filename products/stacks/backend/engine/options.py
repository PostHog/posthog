import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .mappings import validate_key
from .types import Binding, EngineError, EngineOptions


def _invalid(option: str) -> EngineError:
    label = option.replace("_", " ")
    return EngineError(
        [
            {
                "code": "invalid_definition",
                "path": option,
                "message": f"Check the {label} supplied for this stack and run diff again.",
            }
        ]
    )


def valid_entity_id(value: object, kind: str) -> bool:
    if kind == "context_page":
        return isinstance(value, str) and validate_key(kind, value) is None
    if type(value) is int:
        return value >= 0
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]+", value))


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _identity(value: object) -> bool:
    return isinstance(value, dict) and _text(value.get("kind")) and _text(value.get("key"))


def _rows(raw: object, option: str) -> Iterator[dict[str, Any]]:
    if not isinstance(raw, list):
        raise _invalid(option)
    for row in raw:
        if not isinstance(row, dict):
            raise _invalid(option)
        yield row


def validate_options(bindings: list[Binding], options: EngineOptions) -> None:
    if not isinstance(options, dict):
        raise _invalid("options")
    renames = options.get("rename_map", {})
    if not isinstance(renames, dict) or not all(_text(old) and _identity(target) for old, target in renames.items()):
        raise _invalid("rename_map")
    for row in _rows(options.get("detach", []), "detach"):
        if not _identity(row):
            raise _invalid("detach")
    for row in _rows(options.get("claimed", []), "claimed"):
        if not all(_text(row.get(field)) for field in ("kind", "stack", "repository")) or not valid_entity_id(
            row.get("entity_id"), row["kind"]
        ):
            raise _invalid("claimed")
    for option, records in (("bindings", bindings), ("existing", options.get("existing", []))):
        seen = set()
        for row in _rows(records, option):
            if not _identity(row) or not valid_entity_id(row.get("entity_id"), row["kind"]):
                raise _invalid(option)
            if row["kind"] == "context_page" and row["entity_id"] != row["key"]:
                raise _invalid(option)
            identity = (row["kind"], row["key"])
            if identity in seen or row.get("origin", "created") not in ("created", "adopted"):
                raise _invalid(option)
            if option == "bindings" and row.get("status", "bound") not in ("bound", "pending", "detached"):
                raise _invalid(option)
            seen.add(identity)

    if "timeout_seconds" in options:
        seconds = options["timeout_seconds"]
        if type(seconds) not in (int, float) or not 0 < seconds <= sys.float_info.max:
            raise _invalid("timeout_seconds")
    for name in ("mirror", "binary"):
        if name in options and not isinstance(options[name], (Path, str)):
            raise _invalid(name)
    for name, value in options.items():
        if name in ("allow_registry", "refresh") and type(value) is not bool:
            raise _invalid(name)
