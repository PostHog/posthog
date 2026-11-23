import re
import json
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

from .types import DiffError, EngineError, Json

PROVIDER_VERSION = "1.0.33-dev.10"
MAPPING_DIR = Path(__file__).with_name("mapping")
SIMPLE_KEY = re.compile(r"[a-z0-9][a-z0-9_-]*")


@cache
def mappings() -> dict[str, dict[str, Any]]:
    return {path.stem: json.loads(path.read_bytes()) for path in sorted(MAPPING_DIR.glob("*.json"))}


def load_mapping(kind: str) -> dict[str, Any]:
    if not isinstance(kind, str) or kind not in mappings():
        raise EngineError(
            [{"code": "kind_unsupported", "message": "Choose a supported definition kind and run check again."}]
        )
    return mappings()[kind]


def validate_key(kind: str, key: str) -> DiffError | None:
    try:
        mapping = load_mapping(kind)
    except EngineError as exc:
        return exc.errors[0]
    natural = mapping["natural_key"]
    pattern = mapping["key_pattern"] if natural and natural.get("definition_key", True) else SIMPLE_KEY
    if (
        isinstance(key, str)
        and len(key) <= mapping.get("key_max_length", 100)
        and re.fullmatch(pattern, key)
        and key not in mapping.get("reserved_keys", ())
        and not key.startswith(tuple(mapping.get("reserved_key_prefixes", ())))
    ):
        try:
            key.encode("utf-8")
        except UnicodeEncodeError:
            pass
        else:
            return None
    error: DiffError = {
        "code": "invalid_definition",
        "message": "Choose a valid key for this definition.",
        "kind": kind,
        "path": "key",
    }
    if isinstance(key, str):
        error["key"] = key
    return error


def owned_fields(kind: str, body: Mapping[str, Json]) -> frozenset[str]:
    mapping = load_mapping(kind)
    paths = (mapping["fields"].keys() | mapping.get("hook_fields", {}).keys()) - mapping["unmanaged"].keys()
    if "owned_filter_keys" in mapping:
        paths.remove("filters")
        paths.update(f"filters.{key}" for key in flag_filter_keys(body.get("filters"), mapping))
    for path in mapping.get("managed_when_set", ()):
        value: object = body
        for part in path.split("."):
            value = value.get(part) if isinstance(value, Mapping) else None
        if value is None:
            paths.discard(path)
    if mapping["hook"] == "source_payload":
        # Connection inputs and table selection share one API object. Locking the entire object would also lock discovered tables.
        paths.difference_update({"payload", "payload.schemas"})
        payload = body.get("payload")
        if isinstance(payload, Mapping):
            paths.update(f"payload.{key}" for key, value in payload.items() if key != "schemas" or value)
    return frozenset(paths)


def flag_filter_keys(value: Json, mapping: dict[str, Any]) -> list[str]:
    return [key for key in mapping["owned_filter_keys"] if isinstance(value, dict) and value.get(key) is not None]


def natural_key_kinds() -> frozenset[str]:
    return frozenset(
        kind
        for kind, mapping in mappings().items()
        if (key := mapping["natural_key"]) and key.get("definition_key", True)
    )


def kind_scopes(kind: str) -> dict[str, list[str]]:
    scopes = load_mapping(kind)["scopes"]
    read = {f"{name}:read" for name in scopes["read"]}
    return {"read": sorted(read), "write": sorted(read | {f"{name}:write" for name in scopes["write"]})}
