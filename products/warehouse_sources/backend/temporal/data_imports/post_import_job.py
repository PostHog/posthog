"""Post-import Temporal workflow for V3 data imports.

On V3 the `external-data-job` workflow ends at extraction: batches land on S3 and a
separate load consumer writes them into Delta Lake. The post-import steps that read the
loaded table (signal emission, semantic enrichment, column statistics, table size,
DuckLake copy) therefore can't run from that workflow without racing the load — the V3
load consumer starts this workflow after the final batch is loaded and the job is
completed (see pipelines/pipeline_v3/load/processor.py). V2 keeps running the same
steps inline from `external-data-job`.
"""

import json
import uuid
import typing
import datetime as dt
import dataclasses

from django.conf import settings
from django.db import close_old_connections

from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.workflow import ParentClosePolicy

from posthog.models.team.team import Team
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.ducklake.ducklake_copy_data_imports_workflow import (
    DataImportsDuckLakeCopyInputs,
    DuckLakeCopyDataImportsWorkflow,
)

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    EmitSignalsActivityInputs,
    emit_signals_enabled_for,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.calculate_table_size import (
    CalculateTableSizeActivityInputs,
    calculate_table_size_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.compute_table_statistics import (
    ComputeTableStatisticsInputs,
    ComputeTableStatisticsWorkflow,
    statistics_enabled,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    _enrichment_pending,
    _statistics_stale,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.enrich_table_semantics import (
    EnrichTableSemanticsInputs,
    EnrichTableSemanticsWorkflow,
    enrichment_enabled,
)

LOGGER = get_logger(__name__)


def build_post_import_workflow_id(job_id: str) -> str:
    """Workflow id for a job's post-import run, keyed by job so a redelivered final
    batch coalesces with (or is rejected against) the run the first delivery started."""
    return f"data-import-post-import-{job_id}"


@dataclasses.dataclass(frozen=True)
class PostImportWorkflowInputs:
    team_id: int
    job_id: str
    schema_id: str
    source_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "job_id": self.job_id,
            "schema_id": self.schema_id,
            "source_id": self.source_id,
        }


@dataclasses.dataclass(frozen=True)
class PostImportContext:
    """Gating context resolved from the DB once the load has finished. Defaults are the
    skip values so a vanished job/schema (deleted mid-flight) skips every step."""

    source_type: str | None = None
    schema_name: str | None = None
    # Pre-sync watermark from the job's schema snapshot — by the time this workflow runs,
    # post-load bookkeeping has already advanced schema.last_synced_at to this sync.
    last_synced_at: str | None = None
    emit_signals_enabled: bool = False
    enrichment_needed: bool = False
    statistics_needed: bool = False


@activity.defn
def resolve_post_import_context_activity(inputs: PostImportWorkflowInputs) -> PostImportContext:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    close_old_connections()

    try:
        job = ExternalDataJob.objects.get(id=inputs.job_id, team_id=inputs.team_id)
        schema = ExternalDataSchema.objects.prefetch_related("source", "table").get(
            id=inputs.schema_id, team_id=inputs.team_id
        )
    except (ExternalDataJob.DoesNotExist, ExternalDataSchema.DoesNotExist):
        logger.warning(
            "Post-import context could not be resolved (job or schema deleted), skipping all steps",
            job_id=inputs.job_id,
            schema_id=inputs.schema_id,
        )
        return PostImportContext()

    # The consumer triggers after _mark_job_completed, but the Completed write is suppressed
    # when the job was cancelled after the final batch passed the gate — don't emit signals
    # or run the fan-out for a job that didn't actually complete.
    if job.status != ExternalDataJob.Status.COMPLETED:
        logger.info(
            "Post-import skipped: job is not completed",
            job_id=inputs.job_id,
            job_status=job.status,
        )
        return PostImportContext()

    source_type = schema.source.source_type
    snapshot = job.schema_snapshot or {}
    last_synced_at = snapshot.get("last_synced_at")

    team = (
        Team.objects.filter(id=inputs.team_id)
        .select_related("organization")
        .only("uuid", "organization_id", "organization__is_ai_data_processing_approved")
        .first()
    )
    ai_data_processing_approved = team is not None and team.organization.is_ai_data_processing_approved is True

    emit_signals = emit_signals_enabled_for(inputs.team_id, source_type, schema.name, ai_data_processing_approved)

    # Same gates create_external_data_job_model_activity applies for V2, but evaluated
    # post-register: columns this sync added are already visible, so enrichment picks
    # them up now instead of on the next sync. Both children re-check and are idempotent.
    table = schema.table
    enrichment_needed = bool(
        ai_data_processing_approved
        and team is not None
        and enrichment_enabled(team)
        and _enrichment_pending(inputs.team_id, table, schema)
    )
    statistics_needed = bool(team is not None and statistics_enabled(team) and _statistics_stale(inputs.team_id, table))

    return PostImportContext(
        source_type=source_type,
        schema_name=schema.name,
        last_synced_at=last_synced_at,
        emit_signals_enabled=emit_signals,
        enrichment_needed=enrichment_needed,
        statistics_needed=statistics_needed,
    )


@workflow.defn(name="data-import-post-import")
class PostImportWorkflow(PostHogWorkflow):
    """Runs the load-dependent post-import steps for a completed V3 import job."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> PostImportWorkflowInputs:
        loaded = json.loads(inputs[0])
        return PostImportWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PostImportWorkflowInputs) -> None:
        ctx = await workflow.execute_activity(
            resolve_post_import_context_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        schema_id = uuid.UUID(inputs.schema_id)

        # Started by registered workflow name (not class import) so warehouse_sources
        # doesn't import the signals product, which depends on it. See external_product_hooks.
        if ctx.source_type is not None and ctx.schema_name is not None and ctx.emit_signals_enabled:
            try:
                await workflow.start_child_workflow(
                    "emit-data-import-signals",
                    EmitSignalsActivityInputs(
                        team_id=inputs.team_id,
                        schema_id=schema_id,
                        source_id=uuid.UUID(inputs.source_id),
                        job_id=inputs.job_id,
                        source_type=ctx.source_type,
                        schema_name=ctx.schema_name,
                        last_synced_at=ctx.last_synced_at,
                    ),
                    id=f"emit-data-import-signals-{inputs.job_id}",
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    # TBD: Signals are currently using video export queue as the main one, comment to clarify
                    task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                    parent_close_policy=ParentClosePolicy.ABANDON,
                    execution_timeout=dt.timedelta(hours=2),
                )
            except WorkflowAlreadyStartedError:
                # A retried post-import run for the same job collides with the child the
                # first run started — that child already covers this job.
                workflow.logger.info(
                    "Signal emission already running for job, skipping",
                    extra={"job_id": inputs.job_id},
                )

        # Keyed per schema so only one runs per schema at a time; a collision means the
        # running one already covers this schema. Fire-and-forget on the metadata queue.
        if ctx.enrichment_needed:
            try:
                await workflow.start_child_workflow(
                    EnrichTableSemanticsWorkflow.run,
                    EnrichTableSemanticsInputs(team_id=inputs.team_id, schema_id=schema_id),
                    id=f"enrich-warehouse-table-semantics-{inputs.schema_id}",
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    task_queue=settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,
                    parent_close_policy=ParentClosePolicy.ABANDON,
                    execution_timeout=dt.timedelta(minutes=30),
                )
            except WorkflowAlreadyStartedError:
                workflow.logger.info(
                    "Semantic enrichment already running for schema, skipping",
                    extra={"schema_id": inputs.schema_id},
                )

        if ctx.statistics_needed:
            try:
                await workflow.start_child_workflow(
                    ComputeTableStatisticsWorkflow.run,
                    ComputeTableStatisticsInputs(team_id=inputs.team_id, schema_id=schema_id),
                    id=f"compute-warehouse-table-statistics-{inputs.schema_id}",
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    task_queue=settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,
                    parent_close_policy=ParentClosePolicy.ABANDON,
                    execution_timeout=dt.timedelta(minutes=30),
                )
            except WorkflowAlreadyStartedError:
                workflow.logger.info(
                    "Column statistics already running for schema, skipping",
                    extra={"schema_id": inputs.schema_id},
                )

        await workflow.execute_activity(
            calculate_table_size_activity,
            CalculateTableSizeActivityInputs(team_id=inputs.team_id, schema_id=inputs.schema_id, job_id=inputs.job_id),
            start_to_close_timeout=dt.timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        try:
            await workflow.start_child_workflow(
                DuckLakeCopyDataImportsWorkflow.run,
                DataImportsDuckLakeCopyInputs(
                    team_id=inputs.team_id,
                    job_id=inputs.job_id,
                    schema_ids=[schema_id],
                ),
                id=f"ducklake-copy-data-imports-{inputs.team_id}-{inputs.schema_id}",
                task_queue=settings.DUCKLAKE_TASK_QUEUE,
                parent_close_policy=ParentClosePolicy.ABANDON,
            )
        except WorkflowAlreadyStartedError:
            workflow.logger.warning(
                "DuckLake copy already running, skipping",
                extra={"schema_id": inputs.schema_id},
            )
