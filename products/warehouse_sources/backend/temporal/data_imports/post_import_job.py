"""Post-import Temporal workflow for data imports.

The single home for the post-import steps that read the loaded table (signal emission,
semantic enrichment, column statistics, table size, DuckLake copy). On V3 the
`external-data-job` workflow ends at extraction: batches land on S3 and a separate load
consumer writes them into Delta Lake, so these steps can't run from that workflow
without racing the load — the load consumer starts this workflow after the final batch
is loaded and the job is completed (see pipelines/pipeline_v3/load/processor.py). On V2
(and zero-batch V3), `external-data-job` starts this workflow after writing the
COMPLETED job status.

Steps are declared in POST_IMPORT_STEPS: each entry carries its gate (evaluated in the
resolve activity, with DB access) and its workflow-side dispatch. The workflow body is
just a loop over the step keys the activity recorded.
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
    """Gating context resolved from the DB once the load has finished.

    `steps` is the ordered list of POST_IMPORT_STEPS keys to run, computed by the resolve
    activity so the workflow's command sequence derives from recorded history only. None
    means the context predates the step list (an in-flight pre-deploy run) — the workflow
    then falls back to deriving the same sequence from the legacy boolean fields, which
    stay populated for that reason.
    """

    source_type: str | None = None
    schema_name: str | None = None
    # Pre-sync watermark from the job's schema snapshot — by the time this workflow runs,
    # post-load bookkeeping has already advanced schema.last_synced_at to this sync.
    last_synced_at: str | None = None
    emit_signals_enabled: bool = False
    enrichment_needed: bool = False
    statistics_needed: bool = False
    steps: list[str] | None = None


@dataclasses.dataclass(frozen=True)
class PostImportGateContext:
    """Activity-side inputs to the step gates. Never serialized: gates run inside
    resolve_post_import_context_activity with full DB access, and only the resulting
    step keys cross into the workflow."""

    team_id: int
    job: ExternalDataJob
    schema: ExternalDataSchema
    source_type: str
    team: Team | None
    ai_data_processing_approved: bool


@dataclasses.dataclass(frozen=True)
class PostImportStep:
    """One load-dependent post-import step.

    `enabled` runs inside the resolve activity (normal Python: DB, feature flags);
    `start` runs inside the workflow and may only issue Temporal commands. Adding a step
    means adding one POST_IMPORT_STEPS entry. Removing or reordering one needs
    workflow.patched() discipline — in-flight runs have its key recorded, so replay must
    still issue its commands (see .claude/rules/temporal-workflow-versioning.md).
    """

    key: str
    enabled: typing.Callable[[PostImportGateContext], bool]
    start: typing.Callable[[PostImportWorkflowInputs, PostImportContext], typing.Awaitable[None]]


def _emit_signals_gate(gate: PostImportGateContext) -> bool:
    return emit_signals_enabled_for(gate.team_id, gate.source_type, gate.schema.name, gate.ai_data_processing_approved)


def _enrichment_gate(gate: PostImportGateContext) -> bool:
    # Same gates create_external_data_job_model_activity applies for V2, but evaluated
    # post-register: columns this sync added are already visible, so enrichment picks
    # them up now instead of on the next sync. Both children re-check and are idempotent.
    return bool(
        gate.ai_data_processing_approved
        and gate.team is not None
        and enrichment_enabled(gate.team)
        and _enrichment_pending(gate.team_id, gate.schema.table, gate.schema)
    )


def _statistics_gate(gate: PostImportGateContext) -> bool:
    return bool(
        gate.team is not None and statistics_enabled(gate.team) and _statistics_stale(gate.team_id, gate.schema.table)
    )


def _always(gate: PostImportGateContext) -> bool:
    return True


async def _start_emit_signals(inputs: PostImportWorkflowInputs, ctx: PostImportContext) -> None:
    # The gate guarantees these when the key is recorded; the guard is type narrowing only.
    if ctx.source_type is None or ctx.schema_name is None:
        return
    # Started by registered workflow name (not class import) so warehouse_sources
    # doesn't import the signals product, which depends on it. See external_product_hooks.
    try:
        await workflow.start_child_workflow(
            "emit-data-import-signals",
            EmitSignalsActivityInputs(
                team_id=inputs.team_id,
                schema_id=uuid.UUID(inputs.schema_id),
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


async def _start_semantic_enrichment(inputs: PostImportWorkflowInputs, ctx: PostImportContext) -> None:
    # Keyed per schema so only one runs per schema at a time; a collision means the
    # running one already covers this schema. Fire-and-forget on the metadata queue.
    try:
        await workflow.start_child_workflow(
            EnrichTableSemanticsWorkflow.run,
            EnrichTableSemanticsInputs(team_id=inputs.team_id, schema_id=uuid.UUID(inputs.schema_id)),
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


async def _start_table_statistics(inputs: PostImportWorkflowInputs, ctx: PostImportContext) -> None:
    try:
        await workflow.start_child_workflow(
            ComputeTableStatisticsWorkflow.run,
            ComputeTableStatisticsInputs(team_id=inputs.team_id, schema_id=uuid.UUID(inputs.schema_id)),
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


async def _start_table_size(inputs: PostImportWorkflowInputs, ctx: PostImportContext) -> None:
    await workflow.execute_activity(
        calculate_table_size_activity,
        CalculateTableSizeActivityInputs(team_id=inputs.team_id, schema_id=inputs.schema_id, job_id=inputs.job_id),
        start_to_close_timeout=dt.timedelta(minutes=10),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )


async def _start_ducklake_copy(inputs: PostImportWorkflowInputs, ctx: PostImportContext) -> None:
    try:
        await workflow.start_child_workflow(
            DuckLakeCopyDataImportsWorkflow.run,
            DataImportsDuckLakeCopyInputs(
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                schema_ids=[uuid.UUID(inputs.schema_id)],
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


EMIT_SIGNALS_STEP = "emit-signals"
SEMANTIC_ENRICHMENT_STEP = "semantic-enrichment"
TABLE_STATISTICS_STEP = "table-statistics"
TABLE_SIZE_STEP = "table-size"
DUCKLAKE_COPY_STEP = "ducklake-copy"

# Ordered registry of every post-import step. This is the future registration point for
# product-owned steps (external_product_hooks-style), so entries stay self-contained:
# gate on the activity side, commands on the workflow side, nothing in the workflow body.
POST_IMPORT_STEPS: tuple[PostImportStep, ...] = (
    PostImportStep(key=EMIT_SIGNALS_STEP, enabled=_emit_signals_gate, start=_start_emit_signals),
    PostImportStep(key=SEMANTIC_ENRICHMENT_STEP, enabled=_enrichment_gate, start=_start_semantic_enrichment),
    PostImportStep(key=TABLE_STATISTICS_STEP, enabled=_statistics_gate, start=_start_table_statistics),
    PostImportStep(key=TABLE_SIZE_STEP, enabled=_always, start=_start_table_size),
    PostImportStep(key=DUCKLAKE_COPY_STEP, enabled=_always, start=_start_ducklake_copy),
)

_STEP_BY_KEY = {step.key: step for step in POST_IMPORT_STEPS}


def _legacy_step_keys(ctx: PostImportContext) -> list[str]:
    """The step sequence the pre-step-list workflow issued, derived from the legacy
    boolean fields. Replay fidelity: an in-flight run whose recorded context predates
    `steps` must produce exactly the commands the old code produced, in the same order —
    including the unconditional table-size and DuckLake steps on skip-all contexts."""
    keys = []
    if ctx.source_type is not None and ctx.schema_name is not None and ctx.emit_signals_enabled:
        keys.append(EMIT_SIGNALS_STEP)
    if ctx.enrichment_needed:
        keys.append(SEMANTIC_ENRICHMENT_STEP)
    if ctx.statistics_needed:
        keys.append(TABLE_STATISTICS_STEP)
    keys.append(TABLE_SIZE_STEP)
    keys.append(DUCKLAKE_COPY_STEP)
    return keys


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
        return PostImportContext(steps=[])

    # The consumer triggers after _mark_job_completed, but the Completed write is suppressed
    # when the job was cancelled after the final batch passed the gate — don't emit signals
    # or run the fan-out for a job that didn't actually complete.
    if job.status != ExternalDataJob.Status.COMPLETED:
        logger.info(
            "Post-import skipped: job is not completed",
            job_id=inputs.job_id,
            job_status=job.status,
        )
        return PostImportContext(steps=[])

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

    gate_ctx = PostImportGateContext(
        team_id=inputs.team_id,
        job=job,
        schema=schema,
        source_type=source_type,
        team=team,
        ai_data_processing_approved=ai_data_processing_approved,
    )
    steps = [step.key for step in POST_IMPORT_STEPS if step.enabled(gate_ctx)]

    return PostImportContext(
        source_type=source_type,
        schema_name=schema.name,
        last_synced_at=last_synced_at,
        emit_signals_enabled=EMIT_SIGNALS_STEP in steps,
        enrichment_needed=SEMANTIC_ENRICHMENT_STEP in steps,
        statistics_needed=TABLE_STATISTICS_STEP in steps,
        steps=steps,
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

        step_keys = ctx.steps if ctx.steps is not None else _legacy_step_keys(ctx)
        for key in step_keys:
            step = _STEP_BY_KEY.get(key)
            if step is None:
                # A newer worker's resolve activity recorded a key this worker doesn't
                # know yet (rolling deploy). Skipping is safe for a fresh run; a replay
                # that recorded the step's commands fails non-deterministic as any
                # removed command would.
                workflow.logger.warning(
                    "Unknown post-import step, skipping",
                    extra={"step": key, "job_id": inputs.job_id},
                )
                continue
            await step.start(inputs, ctx)
