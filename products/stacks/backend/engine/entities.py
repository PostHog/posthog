from __future__ import annotations

import sys
from collections.abc import Iterator
from itertools import islice
from time import monotonic
from typing import Any
from urllib.parse import SplitResult, urlencode

from . import project_api
from .claims import entity_id_key
from .context_pages import read_pages
from .deadline import DEFAULT_TIMEOUT_SECONDS
from .mappings import load_mapping
from .types import Credentials, EngineError, Entity, EntityPage


def _invalid_read() -> EngineError:
    return EngineError(
        [{"code": "entity_read_invalid", "message": "Check the entity IDs, cursor and limit, then try again."}]
    )


def _missing() -> EngineError:
    return EngineError(
        [
            {
                "code": "entity_missing",
                "message": "Check that the selected entity still exists in this project, then try again.",
            }
        ]
    )


def _identifier(row: dict[str, Any]) -> str:
    value = row.get("id")
    if type(value) not in (str, int) or str(value) == "":
        raise _invalid_read()
    return str(value)


def _fields(record: dict[str, Any], fields: set[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for path in sorted(fields):
        keys = path.split(".")
        if keys[-1] in {"id", "created_at", "updated_at", "created_by"}:
            continue
        value: Any = record
        for key in keys:
            if not isinstance(value, dict) or key not in value:
                break
            value = value[key]
        else:
            target = result
            for key in keys[:-1]:
                target = target.setdefault(key, {})
            target[keys[-1]] = value
    return result


def _id(value: Any) -> Any:
    return value.get("id") if isinstance(value, dict) else value


def _tiles(record: dict[str, Any], mapping: dict[str, Any]) -> list[dict[str, Any]]:
    tiles = []
    for tile in record.get("tiles") or []:
        if not isinstance(tile, dict) or tile.get("deleted"):
            continue
        projected = _fields(tile, set(mapping["layout"]["fields"]))
        if tile.get("insight") is not None:
            projected["insight"] = _id(tile["insight"])
            projected.pop("text", None)
        elif isinstance(tile.get("text"), dict) and isinstance(tile["text"].get("body"), str):
            projected.pop("insight", None)
        else:
            continue
        tiles.append(projected)
    return tiles


def _input_schema(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Input values and schema defaults can come from secrets even when a template has no secret marker.
    fields = {"key", "type", "label", "description", "required", "secret", "hidden", "searchable", "templating"}
    return [_fields(item, fields) for item in value if isinstance(item, dict)]


def _project(
    kind: str, mapping: dict[str, Any], record: dict[str, Any], credentials: Credentials, deadline: float
) -> Entity:
    entity_id = _identifier(record)
    # A null attribute marks a server-only field, which an adopted definition cannot carry.
    settable = {path for path, attribute in mapping["unmanaged"].items() if attribute is not None}
    fields = set(mapping["fields"]) | settable | set(mapping.get("hook_fields", {}))
    read = mapping["read_api"]
    body = _fields(record, fields.difference(read.get("omit", ())))
    for key in read.get("id_fields", ()):
        if key in body:
            value = body[key]
            body[key] = [_id(item) for item in value] if isinstance(value, list) else _id(value)
    for key, allowed in read.get("list_fields", {}).items():
        if isinstance(body.get(key), list):
            body[key] = [_fields(item, set(allowed)) for item in body[key] if isinstance(item, dict)]
    for key, allowed in read.get("object_fields", {}).items():
        if isinstance(body.get(key), dict):
            body[key] = _fields(body[key], set(allowed))
    if kind == "dashboard" and "tiles" in record:
        body["tiles"] = _tiles(record, mapping)
    elif kind == "event":
        links = project_api.collection_url(credentials, mapping["read_api"]["links"])._replace(
            query=urlencode({"event_definition": entity_id})
        )
        body["property_groups"] = list(
            dict.fromkeys(
                _id(row["property_group"])
                for row in project_api.rows(credentials, links, deadline)
                if row.get("event_definition") == entity_id and isinstance(_id(row.get("property_group")), str)
            )
        )
    elif kind == "model":
        if isinstance(record.get("columns"), list):
            types = {t: t for t in ("string", "number", "integer", "boolean", "date", "datetime", "json")}
            types.update({"float": "number", "decimal": "number"})
            body["columns"] = {
                col["name"]: types[col["type"]]
                for col in record["columns"]
                if isinstance(col, dict)
                and isinstance(col.get("name"), str)
                and isinstance(col.get("type"), str)
                and col["type"] in types
            }
    elif kind == "source" and isinstance(record.get("schemas"), list):
        body["payload"] = {
            "schemas": [
                {"name": schema["name"], "should_sync": True}
                for schema in record["schemas"]
                if isinstance(schema, dict)
                and schema.get("should_sync") is True
                and isinstance(schema.get("name"), str)
            ]
        }
    elif kind == "destination":
        if isinstance(record.get("template"), dict) and isinstance(template_id := record["template"].get("id"), str):
            body["template_id"] = template_id
        if isinstance(record.get("inputs_schema"), list):
            body["inputs_schema"] = _input_schema(record["inputs_schema"])
        if isinstance(record.get("mappings"), list):
            mappings = []
            for item in record["mappings"]:
                if isinstance(item, dict):
                    projected = _fields(item, {"name", "filters"})
                    if isinstance(item.get("inputs_schema"), list):
                        projected["inputs_schema"] = _input_schema(item["inputs_schema"])
                    mappings.append(projected)
            body["mappings"] = mappings
    name = record.get("name") or record.get("key") or record.get("source_type") or entity_id
    return {"entity_id": entity_id, "name": str(name), "body": body}


def _listed_urls(
    kind: str, credentials: Credentials, collection: SplitResult, read_api: dict[str, Any], deadline: float
) -> Iterator[tuple[str, SplitResult]]:
    seen = set()
    for row in project_api.rows(credentials, collection._replace(query=read_api.get("list_query", "")), deadline):
        entity_id = entity_id_key(kind, _identifier(row))
        if entity_id in seen:
            continue
        seen.add(entity_id)
        detail_key = row.get(read_api.get("detail_key", "id"))
        if type(detail_key) not in (str, int):
            raise _invalid_read()
        yield entity_id, project_api.detail_url(collection, str(detail_key))


def read_entities(
    kind: str, credentials: Credentials, *, ids: list[str] | None = None, cursor: str | None = None, limit: int = 100
) -> EntityPage:
    mapping = load_mapping(kind)
    read_api = mapping["read_api"]
    if type(limit) is not int or limit < 1 or limit >= sys.maxsize:
        raise _invalid_read()
    revision = None
    if kind == "context_page" and ids is None and isinstance(cursor, str):
        cursor, separator, revision = cursor.partition(".")
        if not separator or not revision or len(revision) > 64:
            raise _invalid_read()
    if cursor is not None and (
        not isinstance(cursor, str) or not cursor.isascii() or not cursor.isdecimal() or len(cursor) > 19
    ):
        raise _invalid_read()
    offset = int(cursor or "0")
    if offset + limit >= sys.maxsize:
        raise _invalid_read()
    deadline = monotonic() + DEFAULT_TIMEOUT_SECONDS
    if kind == "context_page":
        return read_pages(credentials, ids, offset, limit, deadline, revision)
    collection = project_api.collection_url(credentials, read_api["collection"], read_api.get("scope", "projects"))
    listed = _listed_urls(kind, credentials, collection, read_api, deadline)
    if ids is None:
        page = list(islice(listed, offset, offset + limit + 1))
        has_more = len(page) > limit
        page = page[:limit]
    else:
        if not isinstance(ids, list) or not all(isinstance(value, str) for value in ids):
            raise _invalid_read()
        ordered = list(dict.fromkeys(entity_id_key(kind, value) for value in ids))
        for value in ordered:
            project_api.detail_url(collection, value)
        selected = ordered[offset : offset + limit]
        has_more = offset + limit < len(ordered)
        if read_api.get("detail_key") and selected:
            wanted = set(selected)
            matches = {}
            for entity_id, url in listed:
                if entity_id in wanted:
                    matches[entity_id] = url
                    if len(matches) == len(wanted):
                        break
            if len(matches) != len(wanted):
                raise _missing()
            page = [(entity_id, matches[entity_id]) for entity_id in selected]
        else:
            page = [(entity_id, project_api.detail_url(collection, entity_id)) for entity_id in selected]
    results = []
    for entity_id, url in page:
        row = project_api.get(credentials, url, deadline)
        if not isinstance(row, dict) or entity_id_key(kind, _identifier(row)) != entity_id:
            raise _missing()
        results.append(_project(kind, mapping, row, credentials, deadline))
    return {"results": results, "next_cursor": str(offset + limit) if has_more else None}
