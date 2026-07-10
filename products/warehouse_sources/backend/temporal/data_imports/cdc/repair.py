"""Repair a broken CDC source.

Recovery counterpart of ``broken.mark_cdc_broken``: once the change-stream resource can be
recreated (the safety net dropped the slot, or someone dropped it on the source database),
repair recreates the engine-side resources against the stored CDC config, resets every
active CDC schema to snapshot mode so it re-syncs from current table state, clears the
``cdc_broken`` markers, and resumes the paused schedules.

WAL between the old slot's last confirmed position and the new slot's consistent point is
gone — the re-snapshot covers current rows, but intermediate changes in that gap (including
their ``_cdc`` history rows) cannot be recovered.

Safeguards, in order:

- a per-source Redis lock rejects concurrent repairs (``CDCRepairInProgress``);
- repair only proceeds on evidence of breakage — a persisted ``cdc_broken`` marker or a
  live probe showing the slot/publication missing — so a stray API call against a healthy
  source can't drop its slot and force a full re-sync of every CDC schema;
- running CDC jobs are cancelled first (a job holding the slot fails
  ``pg_drop_replication_slot``, and a wedged run would block the SKIP-overlap schedules);
- the ``cdc_broken`` markers are cleared only *after* the new slot exists and the schedules
  are resumed, so a failure at any earlier step leaves the broken evidence in place and a
  retry passes the gate and re-runs idempotently.
"""

from __future__ import annotations

import typing

import structlog

from posthog.redis import get_client

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import CDCSourceAdapter, get_cdc_adapter
from products.warehouse_sources.backend.temporal.data_imports.cdc.naming import cdc_qualified_table_name

logger = structlog.get_logger(__name__)

REPAIR_LOCK_TTL_SECONDS = 300


class CDCRepairError(Exception):
    """Repair cannot proceed; the message is user-facing and credential-safe."""


class CDCRepairInProgress(CDCRepairError):
    """Another repair currently holds this source's repair lock."""


def _repair_lock_key(source_id: str) -> str:
    return f"cdc_repair_lock:{source_id}"


def repair_cdc_source(source: ExternalDataSource) -> int:
    """Repair CDC on a source whose change-stream resources were lost.

    Returns the number of CDC schemas reset for re-sync. Raises ``CDCRepairError`` when
    there is nothing to repair (no active CDC schemas, source looks healthy) or
    ``CDCRepairInProgress`` when another repair holds the lock; lets engine/RPC errors
    propagate for the caller to surface — the flow is safe to re-run after any failure.
    """
    redis = get_client()
    lock_key = _repair_lock_key(str(source.id))
    if not redis.set(lock_key, "1", nx=True, ex=REPAIR_LOCK_TTL_SECONDS):
        raise CDCRepairInProgress("A repair is already running for this source. Try again in a few minutes.")
    try:
        return _repair_locked(source)
    finally:
        # Best-effort: the TTL reaps the lock if this delete is lost.
        try:
            redis.delete(lock_key)
        except Exception:
            logger.warning("cdc_repair_lock_release_failed", source_id=str(source.id), exc_info=True)


def _repair_locked(source: ExternalDataSource) -> int:
    log = logger.bind(source_id=str(source.id), team_id=source.team_id)

    adapter = get_cdc_adapter(source)
    # Re-asserted here (not just in the viewset) so any future facade caller inherits the
    # guard — repairing a CDC-disabled source would provision resources nothing consumes.
    if not adapter.parse_cdc_config(source).enabled:
        raise CDCRepairError("CDC is not enabled on this source.")

    cdc_schemas = list(
        ExternalDataSchema.objects.filter(
            source=source,
            sync_type=ExternalDataSchema.SyncType.CDC,
            should_sync=True,
        ).exclude(deleted=True)
    )
    if not cdc_schemas:
        raise CDCRepairError("There are no active CDC schemas on this source to repair.")

    _require_broken_evidence(source, adapter, cdc_schemas)
    _cancel_running_cdc_jobs(source, cdc_schemas, log)

    # Reset schemas before touching the slot (same ordering as the extraction activity's
    # slot-invalidation recovery): if recreation fails below, a re-run repeats idempotently
    # and no schema keeps streaming across the gap unnoticed. Deferred runs are dropped —
    # they reference WAL from the dead slot and the re-snapshot supersedes them. The
    # `cdc_broken` markers deliberately survive this step: they are the retry gate.
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

    _resume_schedules(source, cdc_schemas)

    # Only now that the new slot exists and the schedules are resumed: clear the broken
    # evidence. A failure before this point leaves the markers for the retry gate; a
    # failure inside this loop leaves some markers, which also re-opens the gate.
    for schema in cdc_schemas:
        update_sync_type_config_keys(
            schema.id,
            source.team_id,
            removes=["cdc_broken"],
            extra_model_fields={"latest_error": None},
        )

    _trigger_resnapshots(cdc_schemas, log)

    log.info("cdc_repair_complete", schemas_reset=len(cdc_schemas))
    return len(cdc_schemas)


def _require_broken_evidence(
    source: ExternalDataSource, adapter: CDCSourceAdapter, cdc_schemas: list[ExternalDataSchema]
) -> None:
    """Refuse to repair a source that looks healthy.

    Repair drops and recreates the slot and forces a full re-sync of every CDC schema, so
    it must not be reachable as a no-questions-asked API mutation. Evidence is either a
    persisted ``cdc_broken`` marker or a live probe showing the slot/publication missing
    (covers a slot dropped on the source database before any extraction run noticed).
    """
    if any((schema.sync_type_config or {}).get("cdc_broken") for schema in cdc_schemas):
        return

    live_status = adapter.get_status(source)
    if live_status.get("slot_exists") is False or live_status.get("publication_exists") is False:
        return

    raise CDCRepairError(
        "CDC looks healthy on this source — the replication slot and publication both exist. "
        "Repair is only available when one of them is missing, because it forces a full re-sync "
        "of every CDC schema."
    )


def _cancel_running_cdc_jobs(
    source: ExternalDataSource, cdc_schemas: list[ExternalDataSchema], log: typing.Any
) -> None:
    """Cancel running CDC jobs' workflows before touching the slot.

    A run still holding the slot makes ``pg_drop_replication_slot`` fail, and a wedged
    Running workflow would block the resumed SKIP-overlap schedules from firing.
    Best-effort per job: cancellation of an already-dead workflow must not block repair.
    """
    # Deferred: data_load.service participates in the CDC schedule<->workflow import cycle.
    from products.data_warehouse.backend.facade.api import cancel_external_data_workflow

    running_jobs = ExternalDataJob.objects.filter(
        pipeline_id=source.pk,
        team_id=source.team_id,
        status=ExternalDataJob.Status.RUNNING,
        schema_id__in=[schema.id for schema in cdc_schemas],
    ).exclude(workflow_id__isnull=True)
    for job in running_jobs:
        if not job.workflow_id:
            continue
        try:
            cancel_external_data_workflow(job.workflow_id)
        except Exception:
            log.warning("cdc_repair_cancel_workflow_failed", workflow_id=job.workflow_id, exc_info=True)


def _resume_schedules(source: ExternalDataSource, cdc_schemas: list[ExternalDataSchema]) -> None:
    # Deferred: data_load.service participates in the CDC schedule<->workflow import cycle.
    from products.data_warehouse.backend.facade.api import (
        sync_cdc_extraction_schedule,
        unpause_cdc_extraction_schedule,
        unpause_external_data_schedule,
    )

    for schema in cdc_schemas:
        unpause_external_data_schedule(str(schema.id))

    # Recreate the extraction schedule if it's gone (e.g. deleted out-of-band) — unpausing
    # a missing schedule is a no-op and would leave CDC repaired but never extracting.
    sync_cdc_extraction_schedule(source)
    unpause_cdc_extraction_schedule(str(source.id))


def _trigger_resnapshots(cdc_schemas: list[ExternalDataSchema], log: typing.Any) -> None:
    """Kick each schema's re-snapshot now instead of waiting out a full sync interval.

    Best-effort: the schedules are already unpaused, so a failed trigger only delays the
    re-sync until the next interval — it must not fail a repair that has already succeeded.
    """
    # Deferred: data_load.service participates in the CDC schedule<->workflow import cycle.
    from products.data_warehouse.backend.facade.api import trigger_external_data_workflow

    for schema in cdc_schemas:
        try:
            trigger_external_data_workflow(schema)
        except Exception:
            log.warning("cdc_repair_trigger_failed", schema_id=str(schema.id), exc_info=True)
