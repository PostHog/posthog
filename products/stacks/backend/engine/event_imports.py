from collections import defaultdict
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from . import project_api
from .addresses import EVENT_LINK, address, decode_address, event_group_key
from .translate_in import event_link_import
from .types import Credentials, EngineError, EngineInput


def _unreadable() -> EngineError:
    return EngineError(
        [{"code": "lookup_failed", "message": "Check the event and property group bindings and run diff again."}]
    )


def _uuid(value: object) -> str:
    if isinstance(value, str):
        try:
            return str(UUID(value))
        except ValueError:
            pass
    raise _unreadable()


def membership_moves(plan: dict[str, Any]) -> list[dict[str, str]]:
    """Keep a link's remote ID when only the representation of its group changed."""
    pairs: dict[tuple[str, str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in plan.get("resource_changes", ()):
        target, change = row["address"], row["change"]
        if not target.startswith(EVENT_LINK + ".") or not (identity := decode_address(target)):
            continue
        actions = change["actions"]
        if actions not in (["create"], ["delete"]):
            continue
        values = change.get("after" if actions == ["create"] else "before") or {}
        event_id, group_id = values.get("event_definition"), values.get("property_group_id")
        if isinstance(event_id, str) and isinstance(group_id, str):
            pairs[identity[1], _uuid(event_id), _uuid(group_id)][actions[0]].append(target)
    return [
        {"from": members["delete"][0], "to": members["create"][0]}
        for members in pairs.values()
        if len(members["delete"]) == 1 and len(members["create"]) == 1
    ]


def event_imports(
    engine_input: EngineInput,
    occupied: set[str],
    known_ids: Mapping[str, str | int],
    credentials: Credentials,
    deadline: float,
) -> list[dict[str, str]]:
    config = engine_input.config
    ids = dict(known_ids)
    occupied = occupied | {block["to"] for block in config.get("import", [])}
    for move in config.get("moved", []):
        if move["from"] in occupied:
            occupied.add(move["to"])
        if move["from"] in ids:
            ids.setdefault(move["to"], ids[move["from"]])

    wanted: dict[tuple[str, str], dict[str, tuple[str, bool]]] = defaultdict(dict)
    desired: set[tuple[str, str]] = set()
    for label, fields in config.get("resource", {}).get(EVENT_LINK, {}).items():
        target = f"{EVENT_LINK}.{label}"
        identity = decode_address(target)
        group_key = event_group_key(target)
        if not identity or group_key is None:
            continue
        event_key = identity[1]
        event_id = ids.get(address("event", event_key))
        literal = not fields["property_group_id"].startswith("${")
        group_id = group_key if literal else ids.get(address("property_group", group_key))
        if event_id is None or group_id is None:
            continue
        pair = (_uuid(event_id), _uuid(group_id))
        if pair in desired:
            raise EngineError(
                [
                    {
                        "code": "binding_conflict",
                        "message": "Choose each property group only once for this event.",
                        "kind": "event",
                        "key": event_key,
                    }
                ]
            )
        desired.add(pair)
        if target not in occupied:
            wanted[event_key, pair[0]][pair[1]] = group_key, literal

    imports = []
    held_links = {_uuid(ids[target]) for target in occupied if target.startswith(EVENT_LINK + ".") and target in ids}
    for (event_key, event_id), groups in wanted.items():
        url = project_api.collection_url(credentials, "event_schemas")._replace(
            query=urlencode({"event_definition": event_id})
        )
        matched: dict[str, tuple[str, str]] = {}
        for row in project_api.rows(credentials, url, deadline):
            if _uuid(row.get("event_definition")) != event_id:
                continue
            group = row.get("property_group")
            if not isinstance(group, dict):
                raise _unreadable()
            group_id = _uuid(group.get("id"))
            if group_id not in groups:
                continue
            link_id = _uuid(row.get("id"))
            if link_id in held_links:
                raise EngineError(
                    [
                        {
                            "code": "binding_conflict",
                            "message": "Keep the existing reference to this property group or detach its link before adopting it again.",
                            "kind": "event",
                            "key": event_key,
                        }
                    ]
                )
            name = group.get("name")
            if (
                not isinstance(name, str)
                or not name
                or matched.setdefault(group_id, (link_id, name)) != (link_id, name)
            ):
                raise EngineError(
                    [
                        {
                            "code": "binding_conflict",
                            "message": "Check this event's property group links in PostHog and run diff again.",
                            "kind": "event",
                            "key": event_key,
                        }
                    ]
                )
        for group_id, (_, name) in matched.items():
            group_key, literal = groups[group_id]
            imports.append(event_link_import(event_key, group_key, name, literal=literal))
    return sorted(imports, key=lambda block: block["to"])
