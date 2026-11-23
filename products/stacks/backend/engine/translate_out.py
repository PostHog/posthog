from __future__ import annotations

import re
import json
from collections.abc import Iterable, Iterator, Mapping
from typing import Any
from urllib.parse import quote, quote_plus

from .addresses import EVENT_LINK, decode_address, event_group_key
from .claims import adoption_id
from .expressions import contains_secret
from .mappings import flag_filter_keys, load_mapping
from .types import (
    ACTIONS,
    Action,
    Change,
    Diff,
    DiffError,
    Drift,
    DriftField,
    EngineError,
    FieldChange,
    Json,
    StackDescription,
)

_MISSING_ENTITY = "PostHog could not find the bound entity. Check the project and binding, then run diff again."
_PROTECTED = "This definition protects its entity from removal. Detach its binding in PostHog to manage it there."
_TILES_RELEASED = "The dashboard tiles stay in PostHog and are no longer managed in code."
STACK_INTERRUPTED_MESSAGE = "The stack stopped unexpectedly. Run diff again. Contact support if it happens again."
_ERROR_RULES = (
    (
        "context_layer_not_enabled",
        r"context layer is not enabled for (?:this )?project",
        "The context layer is not enabled for this project. Enable it in PostHog and run diff again.",
    ),
    (
        "context_page_managed_twice",
        r'context page "" is managed twice in this organization',
        "Two definitions manage this wiki path in your organization. Keep one definition for this path and run diff again.",
    ),
    (
        "context_page_write_uncertain",
        r'context wiki revision conflict writing "" \(current head [^)]+\)\. The previous PUT may have been applied',
        "PostHog may have saved this page. Check the published content and run diff again before pushing.",
    ),
    (
        "stack_moved",
        r"context wiki revision conflict",
        "The wiki changed after this diff. Run diff again and review the page before pushing.",
    ),
    (
        "stack_moved",
        r"saved plan is stale|different state lineage|does not match the given state",
        "This stack changed after you ran diff. Run diff again and review the changes before pushing.",
    ),
    (
        "stack_locked",
        r"acquiring the state lock|state is locked|already locked",
        "Another push is using this stack. Wait for it to finish, then run diff again.",
    ),
    ("removal_blocked", r"cannot be destroyed|prevent_destroy", _PROTECTED),
    (
        "reference_cycle",
        r"\bcycle:",
        "These definitions refer back to each other. Remove one of the references and run check again.",
    ),
    (
        "reference_missing",
        r"reference to undeclared|undeclared resource|unknown reference|reference to undefined",
        "A referenced definition is missing. Check its kind and key, then run check again.",
    ),
    (
        "credentials_invalid",
        r"(?:status|HTTP)\s+(?:401|403)\b|unauthori[sz]ed|forbidden|insufficient.scope|authentication failed|missing api key",
        "PostHog could not authorize this request. Check that your API key has access to the project and the permissions this definition needs.",
    ),
    ("entity_missing", r"(?:status|HTTP)\s+404\b|cannot import non-existent remote object|not.found", _MISSING_ENTITY),
    (
        "entity_exists",
        r"(?:status|HTTP)\s+409\b|already exists|unique constraint",
        "An entity with this key already exists. Adopt its binding or choose a different key, then run diff again.",
    ),
    (
        "body_invalid",
        r"(?:status|HTTP)\s+(?:400|422)\b|validation_error",
        "PostHog rejected a field in this definition. Check its value and run diff again.",
    ),
    (
        "connection_timeout",
        r"(?:status|HTTP)\s+(?:408|504)\b|timed? out|timeout|deadline exceeded",
        "PostHog did not respond in time. Check the connection and run diff again before pushing.",
    ),
    (
        "stack_interrupted",
        r"plugin did not respond|plugin crashed|plugin.*exited|unrecognized remote plugin message|plugin.*unavailable",
        STACK_INTERRUPTED_MESSAGE,
    ),
    (
        "invalid_definition",
        r"invalid|unsupported|extraneous|missing required|incorrect attribute|conflicting configuration|not expected|not enough|too many|argument or block definition required",
        "This definition could not be read. Check its fields and run check again.",
    ),
)
_UNRECOGNIZED = "This stack could not finish. Run diff again. Contact support if it happens again."


def _diagnostics(value: object) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            lines = value.strip().splitlines()
            if lines and all(line.startswith("{") for line in lines):
                for line in lines:
                    try:
                        yield from _diagnostics(json.loads(line))
                    except ValueError:
                        yield {"detail": line}
            else:
                for section in re.split(r"(?m)^(?:│\s*)?Error:\s*", value):
                    if section.strip():
                        yield {"detail": section}
        else:
            if isinstance(parsed, (dict, list)):
                yield from _diagnostics(parsed)
            else:
                yield {"detail": value}
    elif isinstance(value, list):
        for item in value:
            yield from _diagnostics(item)
    elif isinstance(value, Mapping):
        if "diagnostic" in value:
            yield from _diagnostics(value["diagnostic"])
        elif "diagnostics" in value:
            yield from _diagnostics(value["diagnostics"])
        elif value.get("severity", "error") == "error" and ("detail" in value or "summary" in value):
            yield value


_ENGINE_WORDS = re.compile(r"terraform|opentofu|tofu|provider|state|plan|apply|hcl|resource address", re.I)


def _api_reason(response: dict[str, Any], secret_values: Iterable[str]) -> str | None:
    # DRF answers with `detail`. A few views, such as a source's connection check, answer with `message`.
    reason = response.get("detail", response.get("message"))
    if not isinstance(reason, str):
        return None
    variants = {
        form
        for value in secret_values
        if value
        for form in (value, quote(value, safe=""), quote_plus(value, safe=""), json.dumps(value)[1:-1])
    }
    if variants:
        pattern = "|".join(re.escape(value) for value in sorted(variants, key=len, reverse=True))
        reason = re.sub(pattern, "[redacted]", reason)
    reason = " ".join("".join(char if char.isprintable() else " " for char in reason).split())
    if not reason or _ENGINE_WORDS.search(reason):
        return None
    return reason


def translate_error(engine_stderr_or_diagnostics: object, *, secret_values: Iterable[str] = ()) -> list[DiffError]:
    errors: list[DiffError] = []
    secret_values = tuple(secret_values)
    for diag in _diagnostics(engine_stderr_or_diagnostics):
        summary, detail = str(diag.get("summary", "")), str(diag.get("detail", ""))
        # A wiki path can contain braces and words that resemble errors.
        detail_without_paths = re.sub(
            r'(context (?:page|wiki revision conflict writing)) "(?:[^"\\]|\\.)*"', r'\1 ""', detail
        )
        # API responses can quote user input. Classify the transport error before looking inside the body.
        headline = f"{summary}\n{detail_without_paths.partition('{')[0]}"
        rule = next(
            ((code, message) for code, pattern, message in _ERROR_RULES if re.search(pattern, headline, re.I | re.S)),
            ("stack_failed", _UNRECOGNIZED),
        )
        error: DiffError = {"code": rule[0], "message": rule[1]}
        response = {}
        if rule[0] in {"body_invalid", "entity_exists"} and "{" in detail:
            try:
                payload = json.loads(detail[detail.index("{") :])
            except (ValueError, RecursionError):
                payload = None
            if isinstance(payload, dict):
                response = payload
        if rule[0] == "body_invalid" and (reason := _api_reason(response, secret_values)):
            error["message"] = reason
        if rule[0] == "entity_exists" and response.get("code") == "managed_in_code":
            stack = response.get("stack")
            repo = response.get("repository")
            source = response.get("source")
            file = source.get("file") if isinstance(source, dict) else None
            owner = f" by the {stack} stack" if isinstance(stack, str) and stack else ""
            where = f" in {repo}" if isinstance(repo, str) and repo else ""
            edit = file if isinstance(file, str) and file else "the definition"
            error = {
                "code": "managed_in_code",
                "message": f"This entity is managed in code{owner}{where}. Edit {edit}.",
            }
        identity = decode_address(str(diag.get("address", ""))) or _address_in_detail(
            detail_without_paths.partition("{")[0]
        )
        if identity:
            kind, key, _ = identity
            error["kind"] = kind
            error["key"] = key
            if (
                rule[0] == "body_invalid"
                and isinstance(attr := response.get("attr"), str)
                and attr in load_mapping(kind)["fields"]
            ):
                error["path"] = attr
        if error not in errors:
            errors.append(error)
    return errors


# Some diagnostics carry no address and name the resource only in their detail, such as an inconsistent result
# after apply or a blocked destroy. Without this the error names no definition at all.
_DETAIL_ADDRESS = re.compile(r"(?:When applying changes to|Resource instance) (posthog_[a-z_]+\.[A-Za-z0-9_-]+)")


def _address_in_detail(detail: str) -> tuple[str, str, bool] | None:
    match = _DETAIL_ADDRESS.search(detail)
    return decode_address(match.group(1)) if match else None


def _value_at(obj: object, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def _marked(mark: object) -> bool:
    if isinstance(mark, dict):
        return any(_marked(value) for value in mark.values())
    if isinstance(mark, list):
        return any(_marked(value) for value in mark)
    return mark is True


def _child(value: Any, key: str | int) -> Any:
    if isinstance(key, str) and "." in key:
        parent, _, rest = key.partition(".")
        return _child(_child(value, parent), rest)
    if isinstance(value, dict):
        return value.get(key)
    if isinstance(value, list) and isinstance(key, int) and key < len(value):
        return value[key]
    return True if value is True else None


def _sort_sets(value: Json, paths: list[str]) -> Json:
    if "" in paths and isinstance(value, list):
        return sorted(value, key=lambda item: json.dumps(item, sort_keys=True))
    if paths and isinstance(value, dict):
        return {
            key: _sort_sets(
                child,
                [p.removeprefix(key + ".") if p != key else "" for p in paths if p == key or p.startswith(key + ".")],
            )
            for key, child in value.items()
        }
    return value


def _decode_field(value: Any, *, encoded: bool, sets: list[str]) -> Json:
    if encoded and isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            pass
    return _sort_sets(value, sets)


def _fields(
    change: Mapping[str, Any], body: object, mapping: dict[str, Any], *, prefix: str = ""
) -> Iterator[FieldChange]:
    secret_inputs = mapping.get("sensitive_inputs_attribute")
    inputs_changed = secret_inputs and (
        _child(change.get("before"), secret_inputs) != _child(change.get("after"), secret_inputs)
        or _marked(_child(change.get("after_unknown"), secret_inputs))
    )
    for path, attribute in mapping["fields"].items():
        before: Json
        after: Json
        wanted = _value_at(body, path)
        if wanted is None and path in mapping.get("managed_when_set", ()):
            continue
        left = _child(change.get("before"), attribute)
        right = _child(change.get("after"), attribute)
        unknown = _marked(_child(change.get("after_unknown"), attribute))
        if path == "filters" and "owned_filter_keys" in mapping:
            before_filters, after_filters = (_decode_field(value, encoded=True, sets=[]) for value in (left, right))
            sensitive = contains_secret(wanted) or any(
                _marked(_child(change.get(mark), attribute)) for mark in ("before_sensitive", "after_sensitive")
            )
            for key in flag_filter_keys(wanted, mapping):
                before = _child(before_filters, key)
                after = _child(wanted if unknown else after_filters, key)
                if json.dumps(before, sort_keys=True) != json.dumps(after, sort_keys=True):
                    yield {
                        "path": f"{prefix}filters.{key}",
                        "before": None if sensitive else before,
                        "after": None if sensitive else after,
                        "sensitive": sensitive,
                    }
            continue
        sets = [
            item[len(path) :].lstrip(".")
            for item in mapping.get("set_fields", ())
            if item == path or item.startswith(path + ".")
        ]
        before = _decode_field(left, encoded=path in mapping["json_fields"], sets=sets)
        after = wanted if unknown else _decode_field(right, encoded=path in mapping["json_fields"], sets=sets)
        if path in mapping.get("null_values", {}):
            null_value = mapping["null_values"][path]
            before = None if before == null_value else before
            after = None if after == null_value else after
        if path == "inputs" and inputs_changed:
            yield {"path": prefix + path, "before": None, "after": None, "sensitive": True}
            continue
        if mapping.get("hook") == "source_payload" and path == "payload.schemas":
            if not wanted:
                continue
            if isinstance(before, list):
                before = [{"name": name, "should_sync": True} for name in before]
            if isinstance(after, list) and not unknown:
                after = [{"name": name, "should_sync": True} for name in after]
        if json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True) and not unknown:
            continue
        if unknown and after is None and before is None:
            continue
        masked = (
            contains_secret(wanted)
            or (mapping.get("hook") == "source_payload" and path == "payload")
            or any(_marked(_child(change.get(mark), attribute)) for mark in ("before_sensitive", "after_sensitive"))
        )
        yield {
            "path": prefix + path,
            "before": None if masked else before,
            "after": None if masked else after,
            "sensitive": masked,
        }


def _layout_fields(change: Mapping[str, Any], body: object, mapping: dict[str, Any]) -> Iterator[FieldChange]:
    tiles = {key: _child(value, "tiles") for key, value in change.items()}
    wanted = _value_at(body, "tiles")
    count = max(
        (len(items) for items in (tiles.get("before"), tiles.get("after"), wanted) if isinstance(items, list)),
        default=0,
    )
    for index in range(count):
        changed_tile = {key: _child(value, index) for key, value in tiles.items()}
        yield from _fields(changed_tile, _child(wanted, index), mapping["layout"], prefix=f"tiles[{index}].")


def _group_fields(addr: str, change: Mapping[str, Any], body: Mapping[str, Json]) -> list[FieldChange]:
    path = "property_groups"
    before = (change.get("before") or {}).get("property_group_id")
    after = (change.get("after") or {}).get("property_group_id")
    groups = body.get("property_groups")
    if isinstance(groups, list):
        key = event_group_key(addr)
        for index, group in enumerate(groups):
            ref = group.get("$ref") if isinstance(group, dict) else None
            if group == key or isinstance(ref, dict) and ref.get("key") == key:
                path = f"property_groups[{index}]"
                if change.get("after") is not None and after is None:
                    after = group
                break
    if before == after:
        return []
    return [{"path": path, "before": before, "after": after, "sensitive": False}]


def _action(row: Mapping[str, Any]) -> Action | None:
    change = row["change"]
    actions = change.get("actions")
    if actions in (["delete", "create"], ["create", "delete"], ["create", "forget"]):
        return "recreate"
    if actions == ["delete"]:
        return "remove"
    if actions == ["forget"]:
        return "release"
    if change.get("importing") is not None:
        return "adopt"
    if row.get("previous_address"):
        return "rename"
    if actions == ["create"]:
        return "create"
    if actions == ["update"]:
        return "update"
    return None


def _change_summary(action: Action, kind: str, fields: list[FieldChange]) -> str:
    if kind == "context_page":
        kind = "context page"
        if action == "adopt" and any(field["path"] == "content" for field in fields):
            return "Adopt this context page and update its content."
    if action == "update" and fields:
        if len(fields) == 1:
            return f"{fields[0]['path']} changed"
        return f"{len(fields)} fields changed"
    return {
        "create": f"Create this {kind}",
        "remove": f"Remove this {kind}",
        "release": f"This {kind} stays in PostHog and is no longer managed in code.",
        "adopt": f"Bind the existing {kind}",
        "rename": f"Rename the {kind} binding",
        "recreate": f"Recreate this {kind}",
        "update": "PostHog will refresh fields it computes.",
    }[action]


def translate_out(
    plan_json: Mapping[str, Any], description: StackDescription, *, secret_values: Iterable[str] = ()
) -> Diff:
    definitions = {(item["kind"], item["key"]): item for item in description["resources"]}
    changes: dict[tuple[str, str], Change] = {}
    drift: dict[tuple[str, str], Drift] = {}
    errors = translate_error(plan_json.get("diagnostics", []), secret_values=secret_values)
    moves = {
        row["previous_address"]: row["address"]
        for row in plan_json.get("resource_changes", ())
        if "previous_address" in row
    }
    for group in ("resource_changes", "resource_drift"):
        # Process the dashboard before its layout so a tile update contributes fields to the dashboard's action.
        for row in sorted(plan_json.get(group, ()), key=lambda item: item["address"]):
            if row.get("mode", "managed") != "managed":
                continue
            change = row["change"]
            actions = change.get("actions", [])
            action = _action(row)
            if action is None and actions in (["no-op"], ["read"]):
                continue
            addr = row["address"]
            if (
                group == "resource_changes"
                and addr.startswith(EVENT_LINK + ".")
                and action == "rename"
                and actions == ["no-op"]
            ):
                continue
            identity = decode_address(moves.get(addr, addr) if group == "resource_drift" else addr)
            if not identity or action is None:
                error: DiffError = {
                    "code": "binding_unknown",
                    "message": "A binding has no matching definition. Check the rename map and the bindings, then run diff again.",
                }
                if error not in errors:
                    errors.append(error)
                continue
            kind, key, layout = identity
            mapping = load_mapping(kind)
            item = definitions.get((kind, key))
            body = item["body"] if item else {}
            event_link = addr.startswith(EVENT_LINK + ".")
            if action == "release":
                fields = []
            elif event_link:
                fields = _group_fields(addr, change, body)
            else:
                fields = list((_layout_fields if layout else _fields)(change, body, mapping))
            if group == "resource_drift":
                drift_item = drift.setdefault((kind, key), {"kind": kind, "key": key, "fields": []})
                if action == "remove" and not layout:
                    drift_item["deleted"] = True
                for field in fields:
                    drift_field: DriftField = {
                        "path": field["path"],
                        "pushed": field["before"],
                        "found": field["after"],
                    }
                    if field["sensitive"]:
                        drift_field["sensitive"] = True
                    drift_item["fields"].append(drift_field)
                continue
            if "delete" in actions and change.get("importing") is not None:
                errors.append(
                    {
                        "code": "removal_blocked",
                        "message": "This change would delete an entity being adopted. Update the definition to keep the existing entity, then run diff again.",
                        "kind": kind,
                        "key": key,
                    }
                )
            elif not layout and action in ("remove", "recreate") and mapping["removal"] == "prevent":
                errors.append({"code": "removal_blocked", "message": _PROTECTED, "kind": kind, "key": key})
            change_summary = ""
            if event_link and action == "release":
                if (kind, key) in changes:
                    continue
                change_summary = "The property group link stays in PostHog and is no longer managed in code."
            elif layout and action == "release":
                dashboard = changes.get((kind, key))
                if dashboard:
                    if dashboard["action"] != "release":
                        primary = _change_summary(dashboard["action"], kind, dashboard["fields"])
                        dashboard["summary"] = primary.rstrip(".") + ". " + _TILES_RELEASED
                    continue
                change_summary = _TILES_RELEASED
            if event_link or (layout and action not in ("rename", "adopt")):
                action = "update"
            safe_name = body.get("name") if not _marked(_child(change.get("after_sensitive"), "name")) else None
            entry = changes.setdefault(
                (kind, key),
                {
                    "kind": kind,
                    "key": key,
                    "name": safe_name if isinstance(safe_name, str) else key,
                    "action": action,
                    "summary": change_summary,
                    "fields": [],
                    "source": item.get("source") if item else None,
                    "loses": mapping["loses"] if action == "recreate" else None,
                },
            )
            entry["fields"].extend(fields)
            if action == "adopt" and entry["action"] == "adopt":
                try:
                    entry["entity_id"] = adoption_id(kind, change)
                except EngineError as exc:
                    errors.extend(exc.errors)
                    del changes[kind, key]

    summary: dict[Action, int] = dict.fromkeys(ACTIONS, 0)
    for entry in changes.values():
        entry["fields"].sort(key=lambda field: field["path"])
        entry["summary"] = entry["summary"] or _change_summary(entry["action"], entry["kind"], entry["fields"])
        summary[entry["action"]] += 1
    return {
        "changes": [changes[key] for key in sorted(changes)],
        "drift": [drift[key] for key in sorted(drift) if drift[key]["fields"] or drift[key].get("deleted")],
        "summary": summary,
        "errors": errors,
    }
