from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any
from uuid import UUID

from .addresses import EVENT_LINK, decode_address
from .mappings import load_mapping
from .types import EngineError

if TYPE_CHECKING:
    from .types import ClaimedEntity


def entity_id_key(kind: str, value: str | int) -> str:
    text = str(value)
    if load_mapping(kind)["id_type"] == "number":
        if text.isascii() and text.isdecimal():
            return text.lstrip("0") or "0"
        return text
    try:
        return str(UUID(text))
    except ValueError:
        return text


def check_claim(claimed: Sequence[ClaimedEntity], kind: str, key: str, entity_id: str | int) -> None:
    if not claimed:
        return
    candidate = entity_id_key(kind, entity_id)
    for claim in claimed:
        if claim["kind"] == kind and entity_id_key(kind, claim["entity_id"]) == candidate:
            raise EngineError(
                [
                    {
                        "code": "claimed_by_other_stack",
                        "message": f"The {claim['stack']} stack in {claim['repository']} manages this {kind}. Detach it there before adopting it here.",
                        "kind": kind,
                        "key": key,
                    }
                ]
            )


def adoption_id(kind: str, change: Mapping[str, Any]) -> str:
    importing = change.get("importing")
    entity_id = importing.get("id") if isinstance(importing, dict) else None
    if load_mapping(kind)["import_id"] == "{name}":
        entity_id = (change.get("before") or {}).get("id") or (change.get("after") or {}).get("id")
    elif isinstance(entity_id, str):
        entity_id = entity_id.rsplit("/", 1)[-1]
    if not isinstance(entity_id, (str, int)) or isinstance(entity_id, bool) or entity_id == "":
        raise EngineError(
            [{"code": "binding_unknown", "message": "Check the bindings and run diff again before pushing."}]
        )
    return entity_id_key(kind, entity_id)


def saved_adoptions(plan_json: Mapping[str, Any]) -> Iterator[tuple[str, str, str]]:
    for row in plan_json.get("resource_changes", ()):
        if row["change"].get("importing") is None or row["address"].startswith(EVENT_LINK + "."):
            continue
        identity = decode_address(row["address"])
        if identity is None:
            raise EngineError(
                [{"code": "binding_unknown", "message": "Check the bindings and run diff again before pushing."}]
            )
        yield identity[0], identity[1], adoption_id(identity[0], row["change"])


def check_binding_identities(addresses_and_ids: Iterable[tuple[str, str | int]]) -> None:
    owners: dict[tuple[str, str], str] = {}
    for address, entity_id in addresses_and_ids:
        identity = decode_address(address)
        if identity is None or address.startswith(EVENT_LINK + "."):
            continue
        kind, key, _ = identity
        if owners.setdefault((kind, entity_id_key(kind, entity_id)), key) != key:
            raise EngineError(
                [
                    {
                        "code": "binding_conflict",
                        "message": "Choose one definition to manage this entity and run diff again.",
                        "kind": kind,
                        "key": key,
                    }
                ]
            )


def check_planned_identities(plan_json: Mapping[str, Any]) -> None:
    owners: list[tuple[str, int | str]] = []
    for row in plan_json.get("resource_changes", ()):
        change = row["change"]
        if row.get("mode", "managed") != "managed" or change["actions"] == ["forget"]:
            continue
        ids = [(change.get("after") or {}).get("id")]
        if "delete" in change["actions"]:
            # Destruction at another address would also delete the entity being adopted here.
            ids.append((change.get("before") or {}).get("id"))
        identity = decode_address(row["address"])
        if (importing := change.get("importing")) and identity and load_mapping(identity[0])["import_id"] != "{name}":
            entity_id = importing.get("id")
            ids.append(entity_id.rsplit("/", 1)[-1] if isinstance(entity_id, str) else entity_id)
        owners.extend(
            (row["address"], entity_id)
            for entity_id in ids
            if isinstance(entity_id, (str, int)) and not isinstance(entity_id, bool)
        )
    check_binding_identities(owners)


def check_saved_claims(plan_json: Mapping[str, Any], claimed: Sequence[ClaimedEntity]) -> None:
    if claimed:
        for kind, key, entity_id in saved_adoptions(plan_json):
            check_claim(claimed, kind, key, entity_id)
        for row in plan_json.get("resource_changes", ()):
            identity = decode_address(row["address"])
            if identity and identity[0] == "context_page" and row["change"]["actions"] != ["forget"]:
                # The path identifies the page across projects even before its first write.
                check_claim(claimed, "context_page", identity[1], identity[1])
    check_planned_identities(plan_json)
