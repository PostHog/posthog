from collections.abc import Mapping
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.source_management import (
    SourceSchema,
    build_default_schemas,
    build_default_sync_settings,
)
from products.warehouse_sources.backend.migration.types import ItemProposal, ProposedRowFilter

_MULTI_VALUE_OPERATORS = ("IN", "NOT IN")


@frozen
class PlannedSchemas:
    # The `schemas` payload for source creation, one entry per discovered table.
    schemas: list[dict[str, Any]]
    # Planned tables that PostHog did not find or cannot sync with these credentials.
    unavailable: tuple[str, ...]


def build_planned_schemas(
    proposal: ItemProposal, source_schemas: list[SourceSchema], permission_errors: Mapping[str, str | None]
) -> PlannedSchemas:
    """Turn the plan into a create payload: PostHog defaults per table, narrowed to what Fivetran synced."""
    if not proposal.schemas:
        return PlannedSchemas(
            schemas=build_default_schemas(source_schemas, permission_errors=permission_errors), unavailable=()
        )

    planned = {schema.name: schema for schema in proposal.schemas}
    syncable: set[str] = set()
    payload: list[dict[str, Any]] = []
    for source_schema in source_schemas:
        plan = planned.get(source_schema.name)
        if plan is None or source_schema.webhook_only or permission_errors.get(source_schema.name):
            payload.append({"name": source_schema.name, "should_sync": False})
            continue

        entry: dict[str, Any] = {
            "name": source_schema.name,
            "should_sync": True,
            **build_default_sync_settings(source_schema),
        }
        column_names = [str(column[0]) for column in source_schema.columns or []]
        if plan.disabled_columns and column_names:
            disabled = set(plan.disabled_columns)
            entry["enabled_columns"] = [name for name in column_names if name not in disabled]
        if plan.row_filters:
            entry["row_filters"] = [_row_filter_payload(row_filter) for row_filter in plan.row_filters]
        payload.append(entry)
        syncable.add(source_schema.name)

    return PlannedSchemas(schemas=payload, unavailable=tuple(name for name in planned if name not in syncable))


def _row_filter_payload(row_filter: ProposedRowFilter) -> dict[str, Any]:
    value: Any = list(row_filter.values) if row_filter.operator in _MULTI_VALUE_OPERATORS else row_filter.values[0]
    return {"column": row_filter.column, "operator": row_filter.operator, "value": value}
