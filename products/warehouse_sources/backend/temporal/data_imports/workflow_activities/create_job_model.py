import uuid
import typing
import datetime as dt
import dataclasses
from typing import Any

from django.db import close_old_connections
from django.db.models import Max
from django.utils import timezone

import posthoganalytics
from structlog.contextvars import bind_contextvars
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.temporal.common.logger import get_logger

from products.data_warehouse.backend.facade.api import delete_external_data_schedule
from products.warehouse_sources.backend.models.column_annotation import WarehouseColumnAnnotation
from products.warehouse_sources.backend.models.column_statistics import WarehouseColumnStatistics
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import HIDDEN_COLUMNS, DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.destinations.enablement import (
    destination_ids_for_run,
    is_multi_destination_enabled,
)
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    data_quality_checks_needed_for,
    emit_signals_enabled_for,
    person_property_sync_enabled_for,
    schema_binding,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.db_retry import (
    retry_on_operational_error,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    get_v3_pipeline_lock_holder,
)
from products.warehouse_sources.backend.temporal.data_imports.schema_flags import is_fast_return_enabled

WAREHOUSE_PIPELINES_V3_FLAG = "warehouse-pipelines-v3"


def is_pipeline_v3_enabled(team_id: int, source_type: str) -> bool:
    try:
        team = Team.objects.only("uuid", "organization_id").get(id=team_id)
    except Team.DoesNotExist:
        return False

    try:
        return bool(
            posthoganalytics.feature_enabled(
                WAREHOUSE_PIPELINES_V3_FLAG,
                str(team.uuid),
                groups={
                    "organization": str(team.organization_id),
                    "project": str(team.id),
                },
                group_properties={
                    "organization": {"id": str(team.organization_id), "source_type": source_type},
                    "project": {"id": str(team.id), "source_type": source_type},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        capture_exception(e)
        return False


LOGGER = get_logger(__name__)


def _statistics_stale(team_id: int, table: DataWarehouseTable | None) -> bool:
    """Whether column statistics need recomputing: no stats yet, or the freshest column row is older
    than the recompute interval. Mirrors compute_table_statistics' own skip check so we don't spawn a
    child that would immediately no-op on every sync."""
    if table is None:
        # First-ever sync — the table is created during it, so let the (post-sync) profiling run once.
        return True
    # Lazy: compute_table_statistics drags deltalake/pyarrow; keep it off this activity's import path.
    from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.compute_table_statistics import (  # noqa: PLC0415
        MIN_RECOMPUTE_INTERVAL,
    )

    latest = (
        WarehouseColumnStatistics.objects.for_team(team_id)
        .filter(table_id=table.id)
        .aggregate(latest=Max("computed_at"))["latest"]
    )
    return latest is None or (timezone.now() - latest) >= MIN_RECOMPUTE_INTERVAL


def _enrichment_pending(team_id: int, table: DataWarehouseTable | None, schema: ExternalDataSchema) -> bool:
    """Whether semantic enrichment has work to do: any column without an annotation, or a missing
    table-level description. Mirrors enrich_table_semantics' skip check. Computed from pre-sync state,
    so columns added by this sync are picked up on the next one (matching the activity's re-sync
    behaviour) rather than re-running enrichment on every sync."""
    if table is None:
        # First-ever sync — nothing is annotated yet, so there is work to do.
        return True
    # Hidden plumbing columns (_dlt_id, partition key, …) are never enriched, so they'd otherwise
    # show up perpetually in `columns - annotated` and keep this returning True on every sync.
    columns = set((table.columns or {}).keys()) - HIDDEN_COLUMNS
    annotated = set(
        WarehouseColumnAnnotation.objects.for_team(team_id)
        .filter(table_id=table.id)
        .values_list("column_name", flat=True)
    )
    new_columns = columns - annotated
    # "" is the table-level annotation; absent description on both schema and annotations means work.
    table_needs_description = not bool(schema.description) and "" not in annotated
    return bool(new_columns or table_needs_description)


def _verify_v3_lock_still_held(team_id: int, schema_id: uuid.UUID) -> None:
    """Fail fast if another run stole the v3 lock during this run's startup window,
    instead of double-writing the Delta table. Best-effort: skipped when Redis is down."""
    run_id = activity.info().workflow_run_id
    if not run_id:
        return
    holder = get_v3_pipeline_lock_holder(team_id, str(schema_id))
    if holder is None:
        return
    if holder != run_id:
        raise ApplicationError(
            "v3 pipeline lock lost to another run before job creation",
            non_retryable=True,
        )


def _build_schema_snapshot(schema: ExternalDataSchema) -> dict[str, Any]:
    return {
        "name": schema.name,
        "sync_type": schema.sync_type,
        "sync_type_config": schema.sync_type_config,
        "sync_frequency_interval": schema.sync_frequency_interval.total_seconds()
        if schema.sync_frequency_interval
        else None,
        "should_sync": schema.should_sync,
        "status": schema.status,
        "last_synced_at": schema.last_synced_at.isoformat() if schema.last_synced_at else None,
        "initial_sync_complete": schema.initial_sync_complete,
    }


@retry_on_operational_error
def _create_job(
    *,
    team_id: int,
    source_id: uuid.UUID,
    schema_id: uuid.UUID,
    pipeline_version: str,
    billable: bool,
    schema_snapshot: dict[str, Any],
    destination_ids: list[str] | None = None,
) -> ExternalDataJob:
    # A deadlock aborts the INSERT without creating a row, so retrying from scratch is safe. This
    # activity has no Temporal-level retry (see external_data_job.py), because a retry after job
    # creation succeeds would create a duplicate job — retrying just the INSERT avoids that.
    return ExternalDataJob.objects.create(
        team_id=team_id,
        pipeline_id=source_id,
        schema_id=schema_id,
        status=ExternalDataJob.Status.RUNNING,
        rows_synced=0,
        workflow_id=activity.info().workflow_id,
        workflow_run_id=activity.info().workflow_run_id,
        pipeline_version=pipeline_version,
        billable=billable,
        schema_snapshot=schema_snapshot,
        destination_ids=destination_ids or [],
    )


# TODO: remove dependency


@dataclasses.dataclass
class CreateExternalDataJobModelActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID
    billable: bool
    is_v3: bool = False

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "schema_id": self.schema_id,
            "source_id": self.source_id,
            "billable": self.billable,
        }


FAST_RETURN_FULL_RUN_INTERVAL = dt.timedelta(hours=24)


def _fast_return_eligible(
    *,
    schema: ExternalDataSchema,
    team_id: int,
    enrichment_needed: bool,
    statistics_needed: bool,
) -> bool:
    """Whether this run may complete on a negative probe instead of extracting.

    Every condition here answers one of two questions: is the schema's own state simple enough
    that "no new source rows" means "nothing to do" (cursor-tracked, past its initial sync, no
    reset or repartition in flight), and does the pipeline owe this schema any repair work that
    only a full run performs? A repair loop that runs solely on the sync path — the managed-view
    sync, DuckLake copies, the person-property prefix sweep — would never run again on a schema
    that always fast-returns, so anything outstanding forces the full path, and
    FAST_RETURN_FULL_RUN_INTERVAL forces one anyway for whatever this list cannot see.
    """
    if not is_fast_return_enabled(schema):
        return False
    if not (schema.is_incremental or schema.is_append):
        return False
    # xmin and CDC keep their cursor outside `incremental_field_last_value`, and a webhook
    # schema's "source" is an S3 prefix rather than a queryable cursor.
    if schema.is_xmin or schema.is_cdc or schema.is_webhook:
        return False
    if not schema.initial_sync_complete or schema.incremental_field_last_value is None:
        return False
    if schema.reset_pipeline:
        return False
    # A lookback deliberately re-reads rows at or before the watermark, so "nothing past the
    # watermark" does not mean the sync would have written nothing.
    if schema.incremental_field_lookback_seconds:
        return False
    if (
        schema.repartition_pending is not None
        or schema.repartition_swap is not None
        or schema.delta_revive_required is not None
    ):
        return False
    if enrichment_needed or statistics_needed:
        return False
    if data_quality_checks_needed_for(team_id, schema.table_id):
        return False

    last_full_run_at = schema.last_full_run_at
    if last_full_run_at is None:
        return False
    try:
        stamped = dt.datetime.fromisoformat(last_full_run_at)
    except (TypeError, ValueError):
        return False
    if stamped.tzinfo is None:
        return False
    return dt.datetime.now(dt.UTC) - stamped < FAST_RETURN_FULL_RUN_INTERVAL


@dataclasses.dataclass(frozen=True)
class CreateExternalDataJobModelActivityOutputs:
    job_id: str
    incremental_or_append: bool
    source_type: str
    schema_name: str
    # ISO timestamp of when the previous sync completed, used to detect new records
    last_synced_at: str | None = None
    emit_signals_enabled: bool = False
    # True when semantic enrichment is permitted (feature flag on AND AI data processing approved).
    enrichment_enabled: bool = False
    # True when column-statistics profiling is permitted (feature flag on). No AI-data-processing consent
    # term: it reads only the Delta log and writes to our own DB — nothing leaves our infra.
    statistics_enabled: bool = False
    # True when enrichment is permitted AND there is actually work to do (unannotated columns or a missing
    # table description). The workflow gates the child on this so a steady-state sync — which re-fires
    # every few minutes — doesn't spawn a workflow + activity that just no-ops.
    enrichment_needed: bool = False
    # True when statistics are permitted AND stale (no row yet, or older than the recompute interval).
    statistics_needed: bool = False
    # True when the schema feeds at least one enabled person-target Customer analytics source, so the
    # workflow should start the person-property sync child. Gated up front to avoid a no-op child per sync.
    person_property_sync_enabled: bool = False
    # True when this run may complete without extracting if the source proves it has nothing new:
    # the schema tracks a cursor, is past its initial sync, and no repair work is outstanding.
    # Computed here because this activity already resolves the repair gates the decision needs.
    # Defaults False so a payload from a worker that predates the field takes the full path.
    fast_return_eligible: bool = False


@activity.defn
def create_external_data_job_model_activity(
    inputs: CreateExternalDataJobModelActivityInputs,
) -> CreateExternalDataJobModelActivityOutputs:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    close_old_connections()

    try:
        source_exists = ExternalDataSource.objects.filter(id=inputs.source_id).exclude(deleted=True).exists()
        schema_exists = ExternalDataSchema.objects.filter(id=inputs.schema_id).exclude(deleted=True).exists()

        if not source_exists or not schema_exists:
            delete_external_data_schedule(str(inputs.schema_id))
            raise Exception("Source or schema no longer exists - deleted temporal schedule")

        schema = ExternalDataSchema.objects.get(team_id=inputs.team_id, id=inputs.schema_id)

        source: ExternalDataSource = schema.source

        pipeline_version = ExternalDataJob.PipelineVersion.V2
        if inputs.is_v3:
            pipeline_version = ExternalDataJob.PipelineVersion.V3
            _verify_v3_lock_still_held(inputs.team_id, inputs.schema_id)

        # Persist the Running status only after the job row exists: a Running schema with no job
        # behind it can never be finalized, so it would stay stuck on Running forever. With the job
        # committed first, the workflow's finalizer can always resolve it and repaint the schema.
        schema.status = ExternalDataSchema.Status.RUNNING
        # Only v3 runs deliver to destinations; v2 has no per-batch queue to carry the ids.
        destination_ids: list[str] = []
        if pipeline_version == ExternalDataJob.PipelineVersion.V3 and is_multi_destination_enabled(
            inputs.team_id, source.source_type
        ):
            destination_ids = destination_ids_for_run(schema)
        job = _create_job(
            team_id=inputs.team_id,
            source_id=inputs.source_id,
            schema_id=inputs.schema_id,
            pipeline_version=pipeline_version,
            billable=inputs.billable,
            schema_snapshot=_build_schema_snapshot(schema),
            destination_ids=destination_ids,
        )
        schema.save(update_fields=["status", "updated_at"])

        logger.info(
            f"Created external data job for external data source {inputs.source_id}",
        )

        # Both downstream gates (signals + semantic enrichment) need the team and its AI-processing consent.
        team = (
            Team.objects.filter(id=inputs.team_id)
            .select_related("organization")
            .only("uuid", "organization_id", "organization__is_ai_data_processing_approved")
            .first()
        )
        ai_data_processing_approved = team is not None and team.organization.is_ai_data_processing_approved is True

        # Whether to emit signals for this source. The gate is owned by the signals product,
        # which registers it via external_product_hooks (signals depends on warehouse_sources,
        # so we must not import it here).
        emit_signals_enabled = emit_signals_enabled_for(
            inputs.team_id, source.source_type, schema.name, ai_data_processing_approved
        )

        # Semantic enrichment runs only when its flag is on AND AI data processing is approved — let the
        # workflow skip the child entirely rather than spawn one that immediately no-ops.
        # Lazy import: enrich_table_semantics is a workflow module; keep it off this activity's import path.
        from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.enrich_table_semantics import (  # noqa: PLC0415
            enrichment_enabled,
        )

        enrichment_should_run = bool(ai_data_processing_approved and team is not None and enrichment_enabled(team))

        # Column-statistics profiling is gated on its feature flag only (no consent term) — let the
        # workflow skip the child rather than spawn a no-op. Lazy import keeps deltalake off this path.
        from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.compute_table_statistics import (  # noqa: PLC0415
            statistics_enabled,
        )

        statistics_should_run = bool(team is not None and statistics_enabled(team))

        # Narrow "permitted" down to "permitted AND has work to do" so steady-state syncs don't spawn
        # no-op metadata workflows. The activities re-check this themselves as a safety net.
        table = schema.table
        enrichment_needed = enrichment_should_run and _enrichment_pending(inputs.team_id, table, schema)
        statistics_needed = statistics_should_run and _statistics_stale(inputs.team_id, table)

        # Whether this schema feeds any enabled person-target Customer analytics source (owned by
        # customer_analytics via external_product_hooks; not imported here).
        person_property_sync_enabled = person_property_sync_enabled_for(inputs.team_id, schema_binding(schema.id))

        fast_return_eligible = _fast_return_eligible(
            schema=schema,
            team_id=inputs.team_id,
            enrichment_needed=enrichment_needed,
            statistics_needed=statistics_needed,
        )

        return CreateExternalDataJobModelActivityOutputs(
            job_id=str(job.id),
            incremental_or_append=schema.is_incremental or schema.is_append or schema.is_webhook,
            source_type=source.source_type,
            schema_name=schema.name,
            last_synced_at=schema.last_synced_at.isoformat() if schema.last_synced_at else None,
            emit_signals_enabled=emit_signals_enabled,
            enrichment_enabled=enrichment_should_run,
            statistics_enabled=statistics_should_run,
            enrichment_needed=enrichment_needed,
            statistics_needed=statistics_needed,
            person_property_sync_enabled=person_property_sync_enabled,
            fast_return_eligible=fast_return_eligible,
        )
    except Exception as e:
        logger.exception(
            f"External data job failed on create_external_data_job_model_activity for {str(inputs.source_id)} with error: {e}"
        )
        raise
