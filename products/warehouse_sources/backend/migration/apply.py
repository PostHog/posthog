import dataclasses
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.source_management import (
    SourceSchema,
    build_default_schemas,
    build_default_sync_settings,
)
from products.warehouse_sources.backend.migration.types import ItemProposal, ProposedRowFilter, ProposedSchema

_MULTI_VALUE_OPERATORS = ("IN", "NOT IN")


class TableOverrideError(ValueError):
    pass


@frozen
class TableOverride:
    vendor_table: str
    # None drops the table from the plan.
    posthog_table: str | None


def with_table_overrides(proposal: ItemProposal, overrides: Sequence[TableOverride]) -> ItemProposal:
    """Apply the mapping the user confirmed: rename a planned table, add an unmatched one, or drop one."""
    if not overrides:
        return proposal
    if proposal.schemas is None:
        raise TableOverrideError("This plan uses PostHog's default tables, so it takes no table overrides.")
    schemas: dict[str, ProposedSchema | None] = {
        schema.vendor_table or schema.name: schema for schema in proposal.schemas
    }
    for override in overrides:
        if override.vendor_table not in schemas and override.vendor_table not in proposal.unmatched_tables:
            raise TableOverrideError(f"`{override.vendor_table}` is not a Fivetran table of this connection.")
        planned = schemas.get(override.vendor_table)
        if override.posthog_table is None:
            schemas[override.vendor_table] = None
        elif planned is None:
            schemas[override.vendor_table] = ProposedSchema(
                name=override.posthog_table, should_sync=True, sync_type=None, vendor_table=override.vendor_table
            )
        else:
            schemas[override.vendor_table] = dataclasses.replace(
                planned, name=override.posthog_table, alternative_names=()
            )
    kept = tuple(schema for schema in schemas.values() if schema is not None)
    duplicates = sorted(name for name, count in Counter(schema.name for schema in kept).items() if count > 1)
    if duplicates:
        raise TableOverrideError(f"More than one Fivetran table maps to `{duplicates[0]}`.")
    return dataclasses.replace(proposal, schemas=kept)


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

    discovered = {source_schema.name: source_schema for source_schema in source_schemas}
    plans: dict[str, ProposedSchema] = {}
    unavailable: list[str] = []
    for plan in proposal.schemas:
        name = _discovered_name(plan, discovered)
        # A table another plan already claimed would take that plan's columns and filters.
        if name is None or name in plans or permission_errors.get(name):
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


def _discovered_name(plan: ProposedSchema, discovered: Mapping[str, SourceSchema]) -> str | None:
    if plan.name in discovered:
        return plan.name
    # A bare name only stands for `schema.table` when the discovered table is in that schema,
    # or when the source does not say which schema it read.
    vendor_schema = plan.name.rpartition(".")[0]
    for name in plan.alternative_names:
        source_schema = discovered.get(name)
        if source_schema is not None and source_schema.source_schema in (None, vendor_schema):
            return name
    return None


def _with_time_of_day(schema: dict[str, Any], proposal: ItemProposal) -> dict[str, Any]:
    return {**schema, "sync_time_of_day": proposal.sync_time_of_day} if proposal.sync_time_of_day else schema


def _row_filter_payload(row_filter: ProposedRowFilter) -> dict[str, Any]:
    value: Any = list(row_filter.values) if row_filter.operator in _MULTI_VALUE_OPERATORS else row_filter.values[0]
    return {"column": row_filter.column, "operator": row_filter.operator, "value": value}
