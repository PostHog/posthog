from pydantic import JsonValue

from posthog.dataclasses import frozen

from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.signals.backend.filter_catalog import SignalFilterSourceDefinition
from products.signals.backend.filter_catalog_schema import CatalogFieldType


@frozen
class CatalogSeed:
    source_product: str
    source_type: str
    adapter_kind: SignalFilterSourceDefinition.AdapterKind
    initial_rollout_state: SignalFilterSourceDefinition.RolloutState
    bundle: dict[str, JsonValue]


def _field(name: str, field_type: CatalogFieldType, description: str, binding: JsonValue) -> JsonValue:
    return {
        "name": name,
        "type": field_type,
        "description": description,
        "binding": binding,
        "missing_value": "empty_array" if field_type.startswith("array<") else "null",
        "malformed_value": "error",
    }


def _json_path(column: str, key: str) -> JsonValue:
    return {"kind": "json_path", "column": column, "path": [key]}


# Bindings follow the issue rows of the Linear warehouse import, which stores nested
# objects as JSON strings (products/warehouse_sources/sources/linear/queries.py).
LINEAR_ISSUE_SEED = CatalogSeed(
    source_product=SignalSourceProduct.LINEAR,
    source_type=SignalSourceType.ISSUE,
    adapter_kind=SignalFilterSourceDefinition.AdapterKind.WAREHOUSE,
    initial_rollout_state=SignalFilterSourceDefinition.RolloutState.INTERNAL,
    bundle={
        "schema_version": 1,
        "fields": [
            _field("team_id", "string", "ID of the Linear team the issue belongs to.", _json_path("team", "id")),
            _field(
                "project_id",
                "string",
                "ID of the issue's project. Null when the issue has no project.",
                _json_path("project", "id"),
            ),
            _field(
                "project_name",
                "string",
                "Name of the issue's project. Null when the issue has no project.",
                _json_path("project", "name"),
            ),
            _field(
                "assignee_id",
                "string",
                "ID of the user assigned to the issue. Null when the issue is unassigned.",
                _json_path("assignee", "id"),
            ),
            _field(
                "state_type",
                "string",
                "Type of the issue's workflow state: triage, backlog, unstarted or started. "
                "Completed and canceled issues never become signals.",
                _json_path("state", "type"),
            ),
            _field(
                "label_names",
                "array<string>",
                "Names of the issue's labels. Empty when the issue has no labels.",
                {"kind": "json_array_map", "column": "labels", "array_path": ["nodes"], "value_path": ["name"]},
            ),
            _field(
                "priority",
                "integer",
                "Priority of the issue: 0 is no priority, 1 is urgent, 2 is high, 3 is normal and 4 is low.",
                {"kind": "column", "column": "priority"},
            ),
        ],
        "starter_expressions": [
            "assignee_id IS NULL",
            "priority IN (1, 2)",
            "state_type IN ('triage', 'unstarted')",
            "NOT has(label_names, 'internal')",
        ],
        "provenance": {"origin": "manual"},
    },
)

CATALOG_SEEDS: tuple[CatalogSeed, ...] = (LINEAR_ISSUE_SEED,)
