import os
import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from products.stacks.backend.engine.mappings import MAPPING_DIR, load_mapping, mappings
from products.stacks.backend.engine.runner import run_diff
from products.stacks.backend.engine.translate_in import translate_in
from products.stacks.backend.engine.types import StackDescription

from .test_binding_lifecycle import _project

ROOT = Path(__file__).resolve().parents[5]
KINDS = (
    "insight",
    "dashboard",
    "alert",
    "destination",
    "flag",
    "cohort",
    "action",
    "source",
    "experiment",
    "survey",
    "event",
    "property_group",
    "model",
    "endpoint",
    "metric",
    "check",
    "context_page",
)


def _group_input_fields() -> list[str]:
    # This serializer has no generated Zod create body yet. Read its declarative fields without starting Django.
    module = ast.parse((ROOT / "posthog/api/schema_property_group.py").read_text())
    group = next(
        node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "SchemaPropertyGroupSerializer"
    )
    meta = next(node for node in group.body if isinstance(node, ast.ClassDef) and node.name == "Meta")
    declarations = {
        target.id: set(ast.literal_eval(node.value))
        for node in meta.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id in ("fields", "read_only_fields")
    }
    read_only_methods = {
        target.id
        for node in group.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "SerializerMethodField"
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    return sorted(declarations["fields"] - declarations["read_only_fields"] - read_only_methods)


@pytest.fixture(scope="module")
def create_fields() -> dict[str, list[str]]:
    script = """
        const schemas = JSON.parse(process.argv[1]);
        const fields = {};
        for (const [kind, { product, name, file }] of Object.entries(schemas)) {
            const api = await import(file ? './' + file : `./services/mcp/src/generated/${product}/api.ts`);
            const schema = typeof api[name] === 'function' ? api[name]() : api[name];
            fields[kind] = Object.keys(schema.shape);
        }
        console.log(JSON.stringify(fields));
    """
    schemas = {
        kind: mapping["api_schema"]
        for kind, mapping in mappings().items()
        if not mapping["api_schema"].get("structural")
    }
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, json.dumps(schemas)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {**json.loads(result.stdout), "property_group": _group_input_fields()}


@pytest.mark.parametrize("kind", KINDS)
def test_create_body_fields_have_a_mapping_or_reason(kind: str, create_fields: dict[str, list[str]]) -> None:
    mapping = load_mapping(kind)
    classified = {
        path.split(".")[0]
        for section in ("fields", "hook_fields", "unmanaged", "gaps")
        for path in mapping.get(section, {})
    }
    typed = {path for path in mapping.get("typed_only", []) if "[]" not in path}
    classified.update(typed)
    composition_fields = {
        "insight": {"query"},
        "dashboard": {"tiles"},
        "event": {"property_groups"},
        "model": {"columns", "is_materialized"},
    }
    assert classified == set(create_fields[kind]) | composition_fields.get(kind, set())
    assert all(reason.strip() for reason in mapping["gaps"].values())


@pytest.mark.parametrize("kind", KINDS)
def test_mapping_targets_writable_attributes_in_pinned_schema(kind: str) -> None:
    mapping = load_mapping(kind)
    schema = json.loads((MAPPING_DIR.parent / "provider_schema.json").read_bytes())
    resources = schema["provider_schemas"]["registry.opentofu.org/posthog/posthog"]["resource_schemas"]
    block = resources[mapping["resource_type"]]["block"]
    attributes = block["attributes"]
    assert attributes["id"]["type"] == mapping["id_type"]
    for path in mapping["fields"].values():
        field_block = block
        *parents, name = path.split(".")
        for parent in parents:
            nested = field_block["block_types"][parent]
            assert nested["nesting_mode"] == "single", path
            field_block = nested["block"]
        attribute = field_block["attributes"][name]
        assert attribute.get("optional") or attribute.get("required"), path
    for field in mapping["json_fields"]:
        assert attributes[mapping["fields"][field]]["type"] == "string"
    for field in mapping["set_fields"]:
        parent, *tail = field.split(".")
        item = attributes[mapping["fields"][parent]]
        for part in tail:
            item = item["nested_type"]["attributes"][part]
        assert item.get("type", [None])[0] == "set" or item.get("nested_type", {}).get("nesting_mode") == "set"
    writable = set(attributes) | block.get("block_types", {}).keys()
    ignored = set(mapping["unmanaged"].values()) - {None}
    assert ignored | set(mapping.get("ignore_attributes", [])) | mapping.get("defaults", {}).keys() <= writable
    if layout := mapping.get("layout"):
        tiles = resources[layout["resource_type"]]["block"]["attributes"]["tiles"]["nested_type"]
        assert tiles["nesting_mode"] == "list"
        assert set(layout["fields"].values()) <= tiles["attributes"].keys()
    if sensitive_inputs := mapping.get("sensitive_inputs_attribute"):
        assert attributes[sensitive_inputs]["sensitive"]


@pytest.mark.skipif(
    not os.environ.get("POSTHOG_STACK_MIRROR") or not shutil.which("tofu"),
    reason="Needs the installed stack mirror and binary.",
)
def test_diff_for_extended_kinds_preserves_secret_fields(tmp_path: Path) -> None:
    description: StackDescription = {
        "version": 1,
        "resources": [
            {"kind": "action", "key": "opened", "body": {"name": "Opened", "steps": [{"event": "opened"}]}},
            {"kind": "cohort", "key": "readers", "body": {"name": "Readers", "is_static": True}},
            {"kind": "flag", "key": "navigation", "body": {"key": "navigation", "active": True}},
            {
                "kind": "experiment",
                "key": "menu",
                "body": {
                    "name": "Menu",
                    "feature_flag_key": {"$ref": {"kind": "flag", "key": "navigation", "attr": "key"}},
                },
            },
            {
                "kind": "source",
                "key": "warehouse",
                "body": {
                    "source_type": "Postgres",
                    "payload": {
                        "host": "db.example.com",
                        "password": {"$secret": "WAREHOUSE_PASSWORD"},
                        "schemas": [{"name": "events", "should_sync": True}],
                    },
                },
            },
            {"kind": "survey", "key": "feedback", "body": {"name": "Feedback", "type": "popover", "questions": []}},
        ],
    }
    translated = translate_in(description, [], {"mirror": os.environ["POSTHOG_STACK_MIRROR"], "refresh": False})
    empty_catalog: dict[str, object] = {"results": [], "next": None}
    with _project({"/api/projects/7/feature_flags/": empty_catalog, "/api/projects/7/surveys/": empty_catalog}) as (
        credentials,
        _,
    ):
        diff, saved, _ = run_diff(
            tmp_path, translated, None, {**credentials, "secrets": {"WAREHOUSE_PASSWORD": "example-secret-value"}}
        )
    assert diff["errors"] == []
    assert saved
    assert diff["summary"]["create"] == 6
    source = next(change for change in diff["changes"] if change["kind"] == "source")
    assert {"path": "payload", "before": None, "after": None, "sensitive": True} in source["fields"]
    assert "example-secret-value" not in json.dumps(diff)
