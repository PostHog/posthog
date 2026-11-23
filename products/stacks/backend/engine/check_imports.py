"""Identify the check a create would upsert so the diff can show and protect its adoption."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from functools import cache
from math import isfinite
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

from . import project_api
from .addresses import address
from .expressions import definition_error
from .mappings import load_mapping
from .translate_in import import_blocks
from .types import Credentials, EngineError, EngineInput, ResourceDescription

Selector = tuple[str, str, str, str]


def _ambiguous(check: ResourceDescription) -> EngineError:
    return definition_error(
        check,
        "",
        "Check the assertion and its subject, or choose the existing check to adopt and run diff again.",
        "binding_conflict",
    )


def _accepted_value(value: Any, column_type: str) -> str | bool | float:
    if not isinstance(value, (str, int, float, bool)):
        raise ValueError
    if isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if column_type.startswith("Bool"):
        if str(value).strip().lower() not in {"true", "false"}:
            raise ValueError
        return str(value).strip().lower() == "true"
    if column_type.startswith(("Int", "UInt", "Float", "Decimal")):
        if isinstance(value, bool):
            raise ValueError
        number = float(value)
        if not isfinite(number) or (column_type.startswith(("Int", "UInt")) and not number.is_integer()):
            raise ValueError
        return number
    if column_type.startswith(("String", "FixedString")):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).lower() if isinstance(value, bool) else str(value)
    return value


def _canonical(config: Any, check_type: str, column_type: str) -> str:
    # PostHog stores normalized config. Names, severity and tags do not participate in its fingerprint.
    if not isinstance(config, dict):
        raise ValueError
    config = dict(config)
    for name in ("lookback_hours", "to_lookback_hours"):
        if config.get(name) is None:
            config.pop(name, None)
    if check_type == "row_count":
        config.setdefault("min", None)
        config.setdefault("max", None)
    for name in ("min", "max", "lookback_hours", "to_lookback_hours", "max_age_minutes"):
        if (value := config.get(name)) is not None:
            number = Decimal(int(value) if isinstance(value, bool) else str(value))
            if not number.is_finite() or number.adjusted() > 4299 or number != number.to_integral_value():
                raise ValueError
            config[name] = int(number)
    if "to_subject_uuid" in config:
        config["to_subject_uuid"] = str(UUID(config["to_subject_uuid"]))
    if check_type == "accepted_values":
        while column_type.endswith(")") and column_type.startswith(("Nullable(", "LowCardinality(")):
            column_type = column_type.split("(", 1)[1][:-1]
        if not isinstance(config.get("values"), list):
            raise ValueError
        values = (_accepted_value(item, column_type) for item in config["values"])
        by_json = {json.dumps(item, allow_nan=False): item for item in values}
        config["values"] = [by_json[key] for key in sorted(by_json)]
    return json.dumps(config, sort_keys=True, allow_nan=False)


def _resolve(
    value: Any,
    known_ids: Mapping[str, str | int],
    definitions: dict[str, ResourceDescription],
    secrets: Mapping[str, str],
) -> Any:
    if isinstance(value, list):
        return [_resolve(child, known_ids, definitions, secrets) for child in value]
    if isinstance(value, dict):
        if "$ref" in value:
            ref = value["$ref"]
            target = address(ref["kind"], ref["key"])
            attr = ref.get("attr", "id")
            if attr == "id":
                return known_ids[target]
            field = definitions[target]["body"].get(attr)
            if isinstance(field, str):
                return field
            raise ValueError
        if "$secret" in value:
            return secrets[value["$secret"]]
        return {key: _resolve(child, known_ids, definitions, secrets) for key, child in value.items()}
    return value


def _selector(
    check: ResourceDescription,
    known_ids: Mapping[str, str | int],
    occupied: set[str],
    definitions: dict[str, ResourceDescription],
    secrets: Mapping[str, str],
) -> tuple[Selector, Any, bool]:
    body = check["body"]
    subject = body["subject_uuid"]
    fresh_subject = False
    if (
        isinstance(subject, dict)
        and isinstance(ref := subject.get("$ref"), dict)
        and ref.get("attr", "id") == "id"
        and ref.get("kind") in ("model", "metric")
    ):
        target = address(str(ref["kind"]), str(ref["key"]))
        fresh_subject = target not in occupied and target not in known_ids
    subject_id = target if fresh_subject else str(UUID(str(_resolve(subject, known_ids, definitions, secrets))))
    subject_type = _resolve(body["subject_type"], known_ids, definitions, secrets)
    check_type = _resolve(body["check_type"], known_ids, definitions, secrets)
    column = _resolve(body.get("column_name") or "", known_ids, definitions, secrets)
    if not all(isinstance(value, str) for value in (subject_type, check_type, column)):
        raise ValueError
    config = _resolve(body.get("config") or {}, known_ids, definitions, secrets)
    return (subject_type, subject_id, check_type, column.strip()), config, fresh_subject


def check_imports(
    engine_input: EngineInput,
    occupied: set[str],
    known_ids: Mapping[str, str | int],
    credentials: Credentials,
    deadline: float | None,
) -> list[dict[str, str]]:
    config = engine_input.config
    taken = occupied | {block["to"] for block in config.get("import", [])}
    taken.update(block["to"] for block in config.get("moved", []) if block["from"] in occupied)
    definitions = {address(item["kind"], item["key"]): item for item in engine_input.description["resources"]}
    wanted: dict[Selector, list[tuple[ResourceDescription, Any]]] = defaultdict(list)
    live_selectors: set[Selector] = set()
    for target, check in definitions.items():
        if check["kind"] != "check" or target in taken:
            continue
        resource_type, label = target.split(".")
        if label not in config.get("resource", {}).get(resource_type, {}):
            continue
        try:
            selector, assertion, fresh = _selector(check, known_ids, taken, definitions, credentials.get("secrets", {}))
        except (KeyError, TypeError, ValueError):
            raise _ambiguous(check) from None
        wanted[selector].append((check, assertion))
        if not fresh:
            live_selectors.add(selector)

    collection = load_mapping("check")["read_api"]["collection"]
    candidates: dict[Selector, dict[str, dict[str, Any]]] = defaultdict(dict)
    if live_selectors:
        url = project_api.collection_url(credentials, collection)
        for row in project_api.rows(credentials, url, deadline):
            if "subject_uuid" in row and row["subject_uuid"] is None:
                continue
            try:
                selector = row["subject_type"], str(UUID(row["subject_uuid"])), row["check_type"], row["column_name"]
                if not all(isinstance(part, str) for part in selector):
                    raise ValueError
            except (KeyError, ValueError, TypeError, AttributeError):
                raise _ambiguous(wanted[next(iter(live_selectors))][0][0]) from None
            if selector in live_selectors:
                if not isinstance(row.get("id"), str) or not isinstance(row.get("config"), dict):
                    raise _ambiguous(wanted[selector][0][0])
                candidates[selector][row["id"]] = row["config"]

    @cache
    def subject_columns(subject_type: str) -> dict[str, dict[str, Any]]:
        url = project_api.collection_url(credentials, collection + "/subjects")._replace(
            query=urlencode({"subject_type": subject_type})
        )
        return {
            row["id"]: row["columns"]
            for row in project_api.rows(credentials, url, deadline)
            if row.get("subject_type") == subject_type and isinstance(row.get("columns"), dict)
        }

    imports = []
    for selector, checks in wanted.items():
        subject_type, subject_id, check_type, column = selector
        matches = candidates[selector]
        if not matches and len(checks) == 1:
            continue
        column_type = ""
        if check_type == "accepted_values" and selector in live_selectors:
            columns = subject_columns(subject_type).get(subject_id)
            if columns is None or not isinstance(column_type := columns.get(column, ""), str):
                raise _ambiguous(checks[0][0])
        seen: set[tuple[str, str]] = set()
        for check, assertion in checks:
            try:
                identity = _canonical(assertion, check_type, column_type)
            except (OverflowError, TypeError, ValueError, KeyError, AttributeError, InvalidOperation):
                raise _ambiguous(check) from None
            found = [
                entity_id for entity_id, stored in matches.items() if json.dumps(stored, sort_keys=True) == identity
            ]
            aliases = {(column_type, identity)}
            if check_type == "accepted_values" and selector not in live_selectors:
                # A new model's column types are established on its first run. Two definitions must stay distinct for every possible type.
                for future_type in ("Bool", "Float", "String"):
                    try:
                        aliases.add((future_type, _canonical(assertion, check_type, future_type)))
                    except (OverflowError, ValueError):
                        continue
            if len(found) > 1 or not aliases.isdisjoint(seen):
                raise _ambiguous(check)
            seen.update(aliases)
            if found:
                imports.extend(
                    import_blocks("check", check["key"], found[0], claimed=engine_input.options.get("claimed", []))
                )
    return imports
