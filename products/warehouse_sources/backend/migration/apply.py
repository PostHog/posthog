from collections.abc import Mapping
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.source_management import (
    SourceSchema,
    build_default_schemas,
    build_default_sync_settings,
)
from products.warehouse_sources.backend.migration.types import ItemProposal, ProposedRowFilter, ProposedSchema

_MULTI_VALUE_OPERATORS = ("IN", "NOT IN")


@frozen
class PlannedSchemas:
    # The `schemas` payload for source creation, one entry per discovered table.
    schemas: list[dict[str, Any]]
    # Planned tables that PostHog did not find or cannot sync with these credentials.
    unavailable: tuple[str, ...]
    # Planned tables that only sync through a webhook, so they start off until one is registered.
    webhook_only: tuple[str, ...]
    # Discovered tables the plan covers, so a webhook may turn on these and no others.
    planned: tuple[str, ...]


def build_planned_schemas(
    proposal: ItemProposal, source_schemas: list[SourceSchema], permission_errors: Mapping[str, str | None]
) -> PlannedSchemas:
    """Turn the plan into a create payload: PostHog defaults per table, narrowed to what Fivetran synced."""
    if proposal.schemas is None:
        defaults = build_default_schemas(source_schemas, permission_errors=permission_errors)
        if proposal.start_paused:
            defaults = [{**schema, "should_sync": False} for schema in defaults]
        return PlannedSchemas(
            schemas=[_with_time_of_day(schema, proposal) for schema in defaults],
            unavailable=(),
            webhook_only=(),
            planned=tuple(schema.name for schema in source_schemas) if not proposal.start_paused else (),
        )

    discovered = {source_schema.name for source_schema in source_schemas}
    plans: dict[str, ProposedSchema] = {}
    unavailable: list[str] = []
    for plan in proposal.schemas:
        name = next((name for name in (plan.name, *plan.alternative_names) if name in discovered), None)
        if name is None or permission_errors.get(name):
            unavailable.append(plan.name)
        else:
            plans[name] = plan

    payload: list[dict[str, Any]] = []
    webhook_only: list[str] = []
    for source_schema in source_schemas:
        table_plan = plans.get(source_schema.name)
        if table_plan is None or source_schema.webhook_only:
            payload.append({"name": source_schema.name, "should_sync": False})
            if table_plan is not None:
                webhook_only.append(source_schema.name)
            continue

        entry: dict[str, Any] = {
            "name": source_schema.name,
            "should_sync": table_plan.should_sync and not proposal.start_paused,
            **build_default_sync_settings(source_schema),
        }
        column_names = [str(column[0]) for column in source_schema.columns or []]
        if table_plan.disabled_columns and column_names:
            disabled = set(table_plan.disabled_columns)
            entry["enabled_columns"] = [name for name in column_names if name not in disabled]
        if table_plan.row_filters:
            entry["row_filters"] = [_row_filter_payload(row_filter) for row_filter in table_plan.row_filters]
        payload.append(_with_time_of_day(entry, proposal))

    return PlannedSchemas(
        schemas=payload,
        unavailable=tuple(unavailable),
        webhook_only=tuple(webhook_only),
        planned=tuple(plans) if not proposal.start_paused else (),
    )


def _with_time_of_day(schema: dict[str, Any], proposal: ItemProposal) -> dict[str, Any]:
    return {**schema, "sync_time_of_day": proposal.sync_time_of_day} if proposal.sync_time_of_day else schema


def _row_filter_payload(row_filter: ProposedRowFilter) -> dict[str, Any]:
    value: Any = list(row_filter.values) if row_filter.operator in _MULTI_VALUE_OPERATORS else row_filter.values[0]
    return {"column": row_filter.column, "operator": row_filter.operator, "value": value}
