from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator

from . import project_api
from .addresses import address
from .claims import check_binding_identities
from .context_pages import existing_pages
from .mappings import load_mapping
from .translate_in import import_blocks
from .types import Credentials, EngineError, EngineInput


def _entities(credentials: Credentials, lookup: str, deadline: float | None) -> Iterator[dict]:
    return project_api.rows(credentials, project_api.collection_url(credentials, lookup), deadline)


def check_import_identities(blocks: list[dict[str, str]]) -> None:
    check_binding_identities((block["to"], block["id"]) for block in blocks)


def natural_imports(
    engine_input: EngineInput,
    occupied: set[str],
    credentials: Credentials,
    *,
    deadline: float | None = None,
    recheck: set[str] | None = None,
    found_ids: dict[str, str | int] | None = None,
) -> list[dict[str, str]]:
    config = engine_input.config
    occupied = occupied | {block["to"] for block in config.get("import", [])}
    occupied.update(block["from"] for block in config.get("removed", []))
    occupied.update(block["to"] for block in config.get("moved", []) if block["from"] in occupied)
    wanted: dict[str, dict[str, str]] = defaultdict(dict)
    seen: set[tuple[str, str]] = set()
    for resource in engine_input.description["resources"]:
        kind, key = resource["kind"], resource["key"]
        natural = load_mapping(kind).get("natural_key")
        if not natural:
            continue
        target = address(kind, key)
        resource_type, label = target.split(".")
        if label not in config.get("resource", {}).get(resource_type, {}):
            continue
        value = resource["body"].get(natural["field"], key)
        if not isinstance(value, str) or (kind, value) in seen:
            raise EngineError(
                [
                    {
                        "code": "binding_conflict",
                        "message": "Give each definition a unique name and run check again.",
                        "kind": kind,
                        "key": key,
                    }
                ]
            )
        seen.add((kind, value))
        if recheck is not None:
            if target not in recheck:
                continue
        elif target in occupied:
            continue
        wanted[kind][value] = key

    imports = []
    for kind, values in wanted.items():
        natural = load_mapping(kind)["natural_key"]
        matched: set[str] = set()
        entities = (
            existing_pages(credentials, values, deadline)
            if kind == "context_page"
            else _entities(credentials, natural["lookup"], deadline)
        )
        for entity in entities:
            value = entity.get(natural["field"])
            if not isinstance(value, str) or value not in values:
                continue
            key = values[value]
            if value in matched or type(entity.get("id")) not in (str, int):
                raise EngineError(
                    [
                        {
                            "code": "binding_conflict",
                            "message": "Choose the entity to adopt and run diff again.",
                            "kind": kind,
                            "key": key,
                        }
                    ]
                )
            matched.add(value)
            if found_ids is not None:
                found_ids[address(kind, key)] = entity["id"]
            imports.extend(import_blocks(kind, key, entity["id"], claimed=engine_input.options.get("claimed", [])))
    check_import_identities([*config.get("import", []), *imports])
    return imports
