import uuid
import typing
import dataclasses
from typing import Any

from django.db import close_old_connections
from django.db.models import Max
from django.utils import timezone

import posthoganalytics
from structlog.contextvars import bind_contextvars
from temporalio import activity

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
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import emit_signals_enabled_for

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
        schema.status = ExternalDataSchema.Status.RUNNING
        schema.save()

        source: ExternalDataSource = schema.source

        pipeline_version = ExternalDataJob.PipelineVersion.V2
        if inputs.is_v3:
            pipeline_version = ExternalDataJob.PipelineVersion.V3

        job = ExternalDataJob.objects.create(
            team_id=inputs.team_id,
            pipeline_id=inputs.source_id,
            schema_id=inputs.schema_id,
            status=ExternalDataJob.Status.RUNNING,
            rows_synced=0,
            workflow_id=activity.info().workflow_id,
            workflow_run_id=activity.info().workflow_run_id,
            pipeline_version=pipeline_version,
            billable=inputs.billable,
            schema_snapshot=_build_schema_snapshot(schema),
        )

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
        )
    except Exception as e:
        logger.exception(
            f"External data job failed on create_external_data_job_model_activity for {str(inputs.source_id)} with error: {e}"
        )
        raise
