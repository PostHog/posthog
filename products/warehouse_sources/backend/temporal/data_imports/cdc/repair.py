"""Repair a broken CDC source.

Recovery counterpart of ``broken.mark_cdc_broken``: once the change-stream resource can be
recreated (the safety net dropped the slot, or someone dropped it on the source database),
repair recreates the engine-side resources against the stored CDC config, resets every
active CDC schema to snapshot mode so it re-syncs from current table state, clears the
``cdc_broken`` markers, and resumes the paused schedules.

WAL between the old slot's last confirmed position and the new slot's consistent point is
gone — the re-snapshot covers current rows, but intermediate changes in that gap (including
their ``_cdc`` history rows) cannot be recovered.

The whole flow is idempotent: a repair that fails partway (engine-side recreation, schedule
RPCs) leaves the broken markers and paused schedules in place and can simply be re-run.
"""

from __future__ import annotations

import structlog

from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import get_cdc_adapter

logger = structlog.get_logger(__name__)


class CDCRepairError(Exception):
    """Repair cannot proceed; the message is user-facing and credential-safe."""


def cdc_qualified_table_name(schema: ExternalDataSchema, default_schema: str | None) -> str:
    """Resolve a CDC schema row to its source-qualified `schema.table` name.

    Prefers stored schema_metadata, then a dotted display name, then the source's
    default schema — so a row stored bare (`orders`) still resolves to its real
    source location (`public.orders`).
    """
    metadata = schema.sync_type_config.get("schema_metadata") or {}
    src_schema = metadata.get("source_schema")
    src_table = metadata.get("source_table_name")
    if isinstance(src_schema, str) and isinstance(src_table, str):
        return f"{src_schema}.{src_table}"
    if "." in schema.name:
        return schema.name
    return f"{default_schema or 'public'}.{schema.name}"


def repair_cdc_source(source: ExternalDataSource) -> int:
    """Repair CDC on a source whose change-stream resources were lost.

    Returns the number of CDC schemas reset for re-sync. Raises ``CDCRepairError`` when
    there is nothing to repair, and lets engine/RPC errors propagate for the caller to
    surface — the flow is safe to re-run after any failure.
    """
    log = logger.bind(source_id=str(source.id), team_id=source.team_id)

    adapter = get_cdc_adapter(source)

    cdc_schemas = list(
        ExternalDataSchema.objects.filter(
            source=source,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
        ).exclude(deleted=True)
    )
    if not cdc_schemas:
        raise CDCRepairError("There are no active CDC schemas on this source to repair.")

    # Reset schemas before touching the slot (same ordering as the extraction activity's
    # slot-invalidation recovery): if recreation fails below, a re-run repeats idempotently
    # and no schema keeps streaming across the gap unnoticed. Deferred runs are dropped —
    # they reference WAL from the dead slot and the re-snapshot supersedes them.
    for schema in cdc_schemas:
        update_sync_type_config_keys(
            schema.id,
            source.team_id,
            updates={"cdc_mode": "snapshot", "reset_pipeline": True},
            removes=["cdc_last_log_position", "cdc_deferred_runs"],
            extra_model_fields={"initial_sync_complete": False},
        )

    default_schema = (source.job_inputs or {}).get("schema")
    resource_fields = adapter.recreate_slot(
        source, tables=[cdc_qualified_table_name(schema, default_schema) for schema in cdc_schemas]
    )

    source.job_inputs = {**(source.job_inputs or {}), **resource_fields}
    source.status = ExternalDataSource.Status.RUNNING
    source.save(update_fields=["job_inputs", "status", "updated_at"])

    # Only after the new slot exists: clear the broken markers and resume schedules, so no
    # snapshot can run before change capture has a consistent point to resume from.
    for schema in cdc_schemas:
        update_sync_type_config_keys(
            schema.id,
            source.team_id,
            removes=["cdc_broken"],
            extra_model_fields={"latest_error": None},
        )

    _resume_schedules(source, cdc_schemas)

    log.info("cdc_repair_complete", schemas_reset=len(cdc_schemas))
    return len(cdc_schemas)


def _resume_schedules(source: ExternalDataSource, cdc_schemas: list[ExternalDataSchema]) -> None:
    # Deferred: data_load.service participates in the CDC schedule<->workflow import cycle.
    from products.data_warehouse.backend.facade.api import (
        trigger_external_data_workflow,
        unpause_cdc_extraction_schedule,
        unpause_external_data_schedule,
    )

    for schema in cdc_schemas:
        # Trigger so the re-snapshot starts now instead of waiting out a full sync interval.
        unpause_external_data_schedule(str(schema.id))
        trigger_external_data_workflow(schema)

    unpause_cdc_extraction_schedule(str(source.id))
