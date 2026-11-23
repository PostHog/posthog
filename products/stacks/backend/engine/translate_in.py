import re
import json
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote
from uuid import UUID

from .addresses import EVENT_LINK, LAYOUT, address, event_link_address
from .claims import check_claim, entity_id_key
from .expressions import BodyExpressions, contains_secret, definition_error, escape_template, field_values
from .mappings import PROVIDER_VERSION, flag_filter_keys, load_mapping, validate_key
from .options import valid_entity_id, validate_options
from .types import (
    Binding,
    ClaimedEntity,
    DiffError,
    EngineError,
    EngineInput,
    EngineOptions,
    Identity,
    Json,
    ResourceDescription,
    StackDescription,
)
from .validation import (
    check_cycles,
    check_limits,
    check_nested_fields,
    check_references,
    check_secret_positions,
    declared_dependencies,
)

_LEGACY_ADDRESS = re.compile(r'([A-Za-z_][\w-]*)\.([A-Za-z_][\w-]*)(?:\[(\d+|"(?:[^"\\]|\\.)*")\])?', re.ASCII)


def import_blocks(
    kind: str, key: str, entity_id: str | int, *, layout: bool = False, claimed: Sequence[ClaimedEntity] = ()
) -> list[dict[str, str]]:
    mapping = load_mapping(kind)
    if not valid_entity_id(entity_id, kind):
        raise definition_error({"kind": kind, "key": key}, "", "Check the entity ID on this binding.")
    check_claim(claimed, kind, key, entity_id)
    import_id = (
        "${var.stack_project_id}/" + escape_template(key)
        if mapping["import_id"] == "{name}"
        else mapping["import_id"].format(entity_id=entity_id)
    )
    targets = [address(kind, key)]
    if layout:
        targets.append(address(kind, key, layout=True))
    return [{"to": target, "id": import_id} for target in targets]


def event_link_import(event_key: str, group_key: str, group_name: str, *, literal: bool = False) -> dict[str, str]:
    return {
        "to": event_link_address(event_key, group_key, literal=literal),
        "id": f"{quote(event_key, safe='')}/{quote(group_name, safe='')}",
    }


def _event_links(resource: ResourceDescription, expressions: BodyExpressions) -> dict[str, dict[str, str]]:
    groups = resource["body"].get("property_groups", [])
    if not isinstance(groups, list):
        raise expressions.error("property_groups", "Choose a list of property groups for this event.")
    links = {}
    for index, group in enumerate(groups):
        path = f"property_groups[{index}]"
        if isinstance(group, str):
            try:
                group_key = str(UUID(group))
            except ValueError:
                raise expressions.error(path, "Choose a property group definition or an existing group ID.") from None
        else:
            ref = group.get("$ref") if isinstance(group, dict) else None
            if (
                not isinstance(ref, dict)
                or ref.get("kind") != "property_group"
                or ref.get("attr", "id") != "id"
                or not isinstance(ref.get("key"), str)
            ):
                raise expressions.error(path, "Choose a property group definition or an existing group ID.")
            group_key = str(ref["key"])
        name = event_link_address(resource["key"], group_key, literal=isinstance(group, str))
        if name in links:
            raise expressions.error(path, "Choose each property group only once for this event.")
        links[name] = {
            "event_definition": "${" + address("event", resource["key"]) + ".id}",
            "property_group_id": expressions.render(group, path),
        }
    return links


def _move(old: str, target: Identity) -> dict[str, str]:
    match = _LEGACY_ADDRESS.fullmatch(old)
    mapping = load_mapping(target["kind"])
    if not match or match[1] not in (mapping["resource_type"], mapping.get("layout", {}).get("resource_type")):
        raise definition_error(target, "", "Check the old definition and its kind in the rename map.")
    instance = match[3]
    if instance and instance.startswith('"'):
        try:
            instance = escape_template(json.dumps(json.loads(instance), ensure_ascii=False))
        except ValueError:
            raise definition_error(target, "", "Check the instance key in the rename map.") from None
    old = f"{match[1]}.{match[2]}" + (f"[{instance}]" if instance else "")
    return {"from": old, "to": address(target["kind"], target["key"], layout=match[1] == LAYOUT)}


def _tiles(value: Json, mapping: dict[str, Any], expressions: BodyExpressions) -> list[dict[str, Json]]:
    if not isinstance(value, list):
        raise expressions.error("tiles", "Use a list of tiles on this dashboard.")
    result = []
    for i, tile in enumerate(value):
        prefix = f"tiles[{i}]"
        if not isinstance(tile, dict) or ("insight" in tile) == ("text" in tile):
            raise expressions.error(prefix, "Choose one insight or one text body for this tile.")
        if "text" in tile:
            text = tile["text"]
            text_body = text.get("body") if isinstance(text, dict) else None
            if not _string_or_reference(text_body):
                raise expressions.error(prefix, "Add a text body to this tile.")
        if "insight" in tile:
            insight = tile["insight"]
            ref = insight.get("$ref") if isinstance(insight, dict) else None
            if not isinstance(ref, dict) or ref.get("kind") != "insight":
                raise expressions.error(prefix, "Choose an insight definition for this tile.", "reference_missing")
        attributes = {}
        for path, item in field_values(tile, mapping["fields"]):
            if path not in mapping["fields"]:
                raise expressions.error(f"{prefix}.{path}", "Remove this unsupported tile field and run check again.")
            attribute = mapping["fields"][path]
            attributes[attribute] = expressions.render(item, f"{prefix}.{path}", as_json=path in mapping["json_fields"])
        result.append(attributes)
    return result


def _string_or_reference(value: Json) -> bool:
    return isinstance(value, str) or (isinstance(value, dict) and value.keys() in ({"$ref"}, {"$secret"}))


def _source_payload(value: Json, mapping: dict[str, Any], expressions: BodyExpressions) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(schemas := value.get("schemas", []), list):
        raise expressions.error("payload.schemas", "List the tables to sync in the source definition.")
    names = []
    for schema in schemas:
        if (
            not isinstance(schema, dict)
            or schema.keys() - {"name", "should_sync"}
            or not _string_or_reference(schema.get("name"))
        ):
            raise expressions.error("payload.schemas", "Give each table a name and remove unsupported sync settings.")
        if schema.get("should_sync", True) is not True:
            raise expressions.error("payload.schemas", "List only the tables this source should sync.")
        names.append(schema["name"])
    inputs = {field: item for field, item in value.items() if field != "schemas"}
    return {
        mapping["fields"]["payload.schemas"]: expressions.render(names, "payload.schemas"),
        mapping["fields"]["payload"]: expressions.render(inputs, "payload", as_json=True),
    }


def _destination_inputs(
    inputs: dict[str, Json], mapping: dict[str, Any], expressions: BodyExpressions
) -> dict[str, Any]:
    sensitive = {key: value for key, value in inputs.items() if contains_secret(value)}
    public = {key: value for key, value in inputs.items() if key not in sensitive}
    result = {mapping["fields"]["inputs"]: expressions.render(public, "inputs", as_json=True)}
    if sensitive:
        result[mapping["sensitive_inputs_attribute"]] = expressions.render(sensitive, "inputs", as_json=True)
    return result


def _attributes(resource: ResourceDescription, mapping: dict[str, Any], expressions: BodyExpressions) -> dict[str, Any]:
    attrs = dict(mapping.get("defaults", {}))
    if mapping["hook"] == "context_page":
        if resource["body"].get("path") != resource["key"]:
            raise expressions.error("path", "Use the definition key as the wiki page path.")
        content = resource["body"].get("content")
        if not isinstance(content, str) or len(content.encode("utf-8")) > 1_000_000:
            raise expressions.error("content", "Give this context page its Markdown text, up to 1,000,000 UTF-8 bytes.")
    fields = mapping["fields"]
    if "owned_filter_keys" in mapping:
        filters = resource["body"].get("filters")
        if filters is not None and not isinstance(filters, dict):
            raise expressions.error("filters", "Give this flag an object for its filters.")
        attrs["owned_filter_keys"] = flag_filter_keys(filters, mapping)
        if "active" in resource["body"] and resource["body"]["active"] is not None:
            attrs["active"] = expressions.render(resource["body"]["active"], "active")
    typed_only = mapping.get("typed_only", [])
    paths = (
        fields.keys()
        | mapping["unmanaged"].keys()
        | mapping.get("hook_fields", {}).keys()
        | mapping["gaps"].keys()
        | set(typed_only)
    )
    accepted_defaults = mapping.get("accepted_defaults", {})
    for path, value in field_values(resource["body"], paths):
        if (
            path in accepted_defaults
            and type(value) is type(accepted_defaults[path])
            and value == accepted_defaults[path]
        ):
            continue
        if (
            path in mapping["unmanaged"]
            or (value is None and path in mapping.get("managed_when_set", ()))
            or path in typed_only
            or ((mapping["hook"], path) in (("dashboard_layout", "tiles"), ("event_schema", "property_groups")))
        ):
            continue
        if mapping["hook"] == "group_properties" and path == "properties" and isinstance(value, list):
            value = [
                {k: v for k, v in prop.items() if k != "enum"} if isinstance(prop, dict) else prop for prop in value
            ]
        if value is None and path in mapping.get("null_values", {}):
            value = mapping["null_values"][path]
        if mapping["hook"] == "alert_config" and path == "config.type":
            if value not in ("TrendsAlertConfig", "HogQLAlertConfig"):
                raise expressions.error(path, "Choose a trends or SQL alert in this definition.")
            continue
        if mapping["hook"] == "source_payload" and path == "payload":
            attrs.update(_source_payload(value, mapping, expressions))
            continue
        if path not in fields:
            raise expressions.error(path, "Remove this unsupported field from the definition and run check again.")
        if mapping["hook"] == "destination_inputs" and path == "inputs" and isinstance(value, dict):
            attrs.update(_destination_inputs(value, mapping, expressions))
            continue
        target = attrs
        *parents, attribute = fields[path].split(".")
        for parent in parents:
            target = target.setdefault(parent, {})
        target[attribute] = (
            expressions.render(value, path, as_json=path in mapping["json_fields"]) if value is not None else None
        )
    if resource["kind"] == "flag" or mapping["import_id"] == "{name}":
        key_field = mapping["natural_key"]["field"]
        key = escape_template(resource["key"])
        if attrs.get(key_field, key) != key:
            raise expressions.error(key_field, "Use the definition key for this field and run check again.")
        attrs[key_field] = key
    ignore = {attr for attr in mapping["unmanaged"].values() if attr}
    ignore.update(mapping.get("ignore_attributes", []))
    if mapping["hook"] == "source_payload" and attrs.get("schemas") == []:
        # PostHog discovers the tables on create. Refresh can report their names after discovery completes.
        ignore.add("schemas")
    lifecycle: dict[str, Any] = {}
    if ignore:
        lifecycle["ignore_changes"] = sorted(ignore)
    if mapping["removal"] == "prevent":
        lifecycle["prevent_destroy"] = True
    if lifecycle:
        attrs["lifecycle"] = lifecycle
    return attrs


def _binding_targets(kind: str, key: str) -> list[str]:
    targets = [address(kind, key)]
    if kind == "dashboard":
        targets.append(address(kind, key, layout=True))
    return targets


def _configure_removals(
    config: dict[str, Any], targets: set[str], bindings: list[Binding], detached: set[tuple[str, str]]
) -> frozenset[tuple[str, str]]:
    release = set()
    for kind, key in detached:
        release.update(_binding_targets(kind, key))
    moved_to = {move["from"]: move["to"] for move in config.get("moved", [])}
    protected = {block["to"] for block in config.get("import", [])}
    adopted_ids = set()
    for binding in bindings:
        kind, key = binding["kind"], binding["key"]
        adopted = binding.get("origin", "created") == "adopted" or binding.get("status") == "pending"
        if adopted:
            adopted_ids.add((kind, entity_id_key(kind, binding["entity_id"])))
        if adopted or load_mapping(kind)["removal"] == "prevent":
            protected.update(moved_to.get(target, target) for target in _binding_targets(kind, key))
    for target in protected:
        if target in targets:
            resource_type, label = target.split(".")
            config["resource"][resource_type][label].setdefault("lifecycle", {})["prevent_destroy"] = True
        else:
            release.add(target)
    if release:
        config["removed"] = [{"from": target, "lifecycle": {"destroy": False}} for target in sorted(release)]
    return frozenset(adopted_ids)


def translate_in(description: StackDescription, bindings: list[Binding], options: EngineOptions) -> EngineInput:
    validate_options(bindings, options)
    if (
        not isinstance(description, dict)
        or type(description.get("version")) is not int
        or description["version"] != 1
        or not isinstance(description.get("resources"), list)
        or description.keys() - {"version", "resources"}
    ):
        raise EngineError(
            [{"code": "invalid_definition", "message": "Run check to generate a version 1 stack definition."}]
        )
    check_limits(description)
    resources: dict[tuple[str, str], ResourceDescription] = {}
    for resource in description["resources"]:
        if (
            not isinstance(resource, dict)
            or not isinstance(resource.get("kind"), str)
            or not isinstance(resource.get("key"), str)
        ):
            raise EngineError(
                [
                    {
                        "code": "invalid_definition",
                        "message": "Give every definition a kind and a key and run check again.",
                    }
                ]
            )
        kind, key = resource["kind"], resource["key"]
        if resource.keys() - {"kind", "key", "body", "source", "depends_on"}:
            raise definition_error(resource, "", "Use only kind, key, body, source and depends_on in a definition.")
        if "source" in resource:
            source = resource["source"]
            if (
                not isinstance(source, dict)
                or set(source) - {"file", "export"}
                or not source.get("file")
                or not all(isinstance(text, str) for text in source.values())
            ):
                raise definition_error(
                    resource, "source", "Give this definition a source file and an optional export name."
                )
        if key_error := validate_key(kind, key):
            raise EngineError([key_error])
        if (kind, key) in resources or not isinstance(resource.get("body"), dict):
            raise definition_error(resource, "", "Give each definition a unique key and an object body.")
        resources[kind, key] = resource

    detached = {(b["kind"], b["key"]) for b in options.get("detach", [])}
    detached.update((b["kind"], b["key"]) for b in bindings if b.get("status") == "detached")
    definitions = resources.keys() - detached
    config: dict[str, Any] = {
        "terraform": {"required_providers": {"posthog": {"source": "PostHog/posthog", "version": PROVIDER_VERSION}}},
        "provider": {"posthog": {}},
    }
    secrets: set[str] = set()
    targets: set[str] = set()
    dependencies = {}
    all_definitions = set(resources)
    for kind, key in sorted(resources):
        resource = resources[kind, key]
        mapping = load_mapping(kind)
        managed = (kind, key) in definitions
        expr = BodyExpressions(resource, definitions if managed else all_definitions, secrets if managed else set())
        check_secret_positions(resource, mapping)
        check_references(resource, BodyExpressions(resource, all_definitions, set()))
        explicit = declared_dependencies(resource, expr.definitions)
        check_nested_fields(resource, mapping)
        primary = address(kind, key)
        resource_type, label = primary.split(".")
        blocks = config.setdefault("resource", {}) if managed else {}
        live_targets = targets if managed else set()
        live_targets.add(primary)
        blocks.setdefault(resource_type, {})[label] = _attributes(resource, mapping, expr)
        # Layouts and event memberships are written after their primary definitions exist.
        dependencies[kind, key] = expr.dependencies | explicit
        if explicit:
            blocks[resource_type][label]["depends_on"] = [address(*identity) for identity in sorted(explicit)]
        if mapping["hook"] == "dashboard_layout" and "tiles" in resource["body"]:
            blocks.setdefault(LAYOUT, {})[label] = {
                "dashboard_id": "${" + primary + ".id}",
                "tiles": _tiles(resource["body"]["tiles"], mapping["layout"], expr),
            }
            live_targets.add(address(kind, key, layout=True))
        if mapping["hook"] == "event_schema":
            for link, attributes in _event_links(resource, expr).items():
                blocks.setdefault(EVENT_LINK, {})[link.split(".")[1]] = attributes
                live_targets.add(link)
    check_cycles(dependencies)
    if secrets:
        config["variable"] = {"stack_secrets": {"type": "map(string)", "sensitive": True}}

    moves = []
    moved_targets = set()
    for old, target in sorted(options.get("rename_map", {}).items()):
        move = _move(old, target)
        if move["to"] not in targets or move["to"] in moved_targets:
            raise definition_error(target, "", "Check that the rename map points to a unique definition in this stack.")
        if move["from"] != move["to"]:
            moves.append(move)
            moved_targets.add(move["to"])
    if moves:
        config["moved"] = moves

    imports = []
    import_entity_ids: dict[str, str | int] = {}
    by_identity = {(b["kind"], b["key"]): b for b in bindings}
    existing = {(b["kind"], b["key"]): b for b in options.get("existing", [])}
    for kind, key in sorted(definitions):
        binding = by_identity.get((kind, key))
        if binding is None and load_mapping(kind)["natural_key"]:
            record = existing.get((kind, key))
        else:
            record = binding if binding and binding.get("status") == "pending" else None
        if record:
            import_entity_ids[address(kind, key)] = record["entity_id"]
            layout = kind == "dashboard" and "tiles" in resources[kind, key]["body"]
            imports.extend(
                import_blocks(kind, key, record["entity_id"], layout=layout, claimed=options.get("claimed", []))
            )
    if imports:
        config["import"] = imports
        if any(block["id"].startswith("${var.stack_project_id}/") for block in imports):
            config.setdefault("variable", {})["stack_project_id"] = {"type": "string"}
    adopted_ids = _configure_removals(config, targets, bindings, detached)
    return EngineInput(
        config=config,
        description=description,
        secret_names=frozenset(secrets),
        options=options,
        adopted_ids=adopted_ids,
        import_entity_ids=import_entity_ids,
    )


def validate_description(description: StackDescription, bindings: list[Binding]) -> list[DiffError]:
    """Return the first problem before the caller stores the description."""
    try:
        translate_in(description, bindings, {})
    except EngineError as error:
        return error.errors
    return []
