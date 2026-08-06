"""The V2/V3 post-import fork in `external-data-job`.

The load-dependent post-import steps run only in `data-import-post-import`: V3 runs
with batches rely on the load consumer to start it after the final batch loads, while
V2 (and zero-batch V3) start it from `external-data-job` after the COMPLETED status
write. If the workflow-side trigger is dropped, V2 syncs silently lose every step; if
it fires before the status write, the resolve activity skips them all; if it
over-applies, V3-with-batches double-triggers or externally managed schemas gain a
fan-out they never had.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from unittest import mock

from temporalio import activity
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.warehouse_sources.backend.temporal.data_imports.external_data_job import (
    CreateSourceTemplateInputs,
    ExternalDataJobWorkflow,
    UpdateExternalDataJobStatusInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.typings import PipelineResult
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock import (
    AcquireV3LockActivityInputs,
    AcquireV3LockActivityOutputs,
    CheckPipelineVersionActivityInputs,
    CheckPipelineVersionActivityOutputs,
    ReleaseV3LockActivityInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.calculate_table_size import (
    CalculateTableSizeActivityInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.check_billing_limits import (
    CheckBillingLimitsActivityInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    CreateExternalDataJobModelActivityInputs,
    CreateExternalDataJobModelActivityOutputs,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportDataActivityInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.repartition_table import (
    RepartitionActivityInputs,
)

_JOB_ID = "01960000-0000-0000-0000-000000000000"


def _stub_activities(
    executed: list[str], *, is_v3: bool, consumer_manages_job_status: bool, skip_post_import_activities: bool = False
) -> list:
    @activity.defn(name="check_pipeline_version_activity")
    async def check_pipeline_version(inputs: CheckPipelineVersionActivityInputs) -> CheckPipelineVersionActivityOutputs:
        executed.append("check_pipeline_version_activity")
        return CheckPipelineVersionActivityOutputs(is_v3=is_v3)

    @activity.defn(name="acquire_v3_pipeline_lock_activity")
    async def acquire_lock(inputs: AcquireV3LockActivityInputs) -> AcquireV3LockActivityOutputs:
        executed.append("acquire_v3_pipeline_lock_activity")
        return AcquireV3LockActivityOutputs(acquired=True, token="token")

    @activity.defn(name="release_v3_pipeline_lock_activity")
    async def release_lock(inputs: ReleaseV3LockActivityInputs) -> None:
        executed.append("release_v3_pipeline_lock_activity")

    @activity.defn(name="create_external_data_job_model_activity")
    async def create_job(inputs: CreateExternalDataJobModelActivityInputs) -> CreateExternalDataJobModelActivityOutputs:
        executed.append("create_external_data_job_model_activity")
        return CreateExternalDataJobModelActivityOutputs(
            job_id=_JOB_ID,
            incremental_or_append=False,
            source_type="Stripe",
            schema_name="Customer",
            last_synced_at=None,
            emit_signals_enabled=True,
            enrichment_needed=True,
            statistics_needed=True,
            person_property_sync_enabled=True,
        )

    @activity.defn(name="check_billing_limits_activity")
    async def check_billing(inputs: CheckBillingLimitsActivityInputs) -> bool:
        executed.append("check_billing_limits_activity")
        return False

    @activity.defn(name="maybe_repartition_table_activity")
    async def maybe_repartition(inputs: RepartitionActivityInputs) -> None:
        executed.append("maybe_repartition_table_activity")

    @activity.defn(name="import_data_activity_sync")
    async def import_data(inputs: ImportDataActivityInputs) -> PipelineResult:
        executed.append("import_data_activity_sync")
        return PipelineResult(
            should_trigger_cdp_producer=False,
            consumer_manages_job_status=consumer_manages_job_status,
            skip_post_import_activities=skip_post_import_activities,
        )

    @activity.defn(name="create_source_templates")
    async def create_templates(inputs: CreateSourceTemplateInputs) -> None:
        executed.append("create_source_templates")

    @activity.defn(name="calculate_table_size_activity")
    async def calculate_table_size(inputs: CalculateTableSizeActivityInputs) -> None:
        executed.append("calculate_table_size_activity")

    @activity.defn(name="update_external_data_job_model")
    async def update_job(inputs: UpdateExternalDataJobStatusInputs) -> None:
        executed.append("update_external_data_job_model")

    return [
        check_pipeline_version,
        acquire_lock,
        release_lock,
        create_job,
        check_billing,
        maybe_repartition,
        import_data,
        create_templates,
        calculate_table_size,
        update_job,
    ]


async def _run_workflow(
    *, is_v3: bool, consumer_manages_job_status: bool, skip_post_import_activities: bool = False
) -> tuple[list[str], list[str]]:
    """Run the workflow with stubbed activities; return (executed activities + child starts in
    order, started child ids)."""
    executed: list[str] = []

    async def record_child_start(*args, **kwargs) -> None:
        executed.append(f"child:{kwargs['id']}")

    with (
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.external_data_job.workflow.start_child_workflow",
            new_callable=mock.AsyncMock,
            side_effect=record_child_start,
        ) as mock_start_child,
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.external_data_job.get_data_import_finished_metric"
        ),
    ):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="test-post-import-fork",
                workflows=[ExternalDataJobWorkflow],
                activities=_stub_activities(
                    executed,
                    is_v3=is_v3,
                    consumer_manages_job_status=consumer_manages_job_status,
                    skip_post_import_activities=skip_post_import_activities,
                ),
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=10),
            ):
                await env.client.execute_workflow(
                    ExternalDataJobWorkflow.run,
                    ExternalDataWorkflowInputs(
                        team_id=1,
                        external_data_source_id=uuid.uuid4(),
                        external_data_schema_id=uuid.uuid4(),
                        billable=False,
                    ),
                    id=str(uuid.uuid4()),
                    task_queue="test-post-import-fork",
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    child_ids = [call.kwargs["id"] for call in mock_start_child.call_args_list]
    return executed, child_ids


LOAD_DEPENDENT_CHILD_PREFIXES = (
    "emit-data-import-signals-",
    "enrich-warehouse-table-semantics-",
    "compute-warehouse-table-statistics-",
    "ducklake-copy-data-imports-",
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_v3,consumer_manages_job_status,skip_post_import_activities,expect_post_import_child",
    [
        # V2: the workflow starts data-import-post-import after the COMPLETED write.
        pytest.param(False, False, False, True, id="v2_starts_post_import_workflow"),
        # V3 with zero batches: the consumer never sees a final batch, so the workflow keeps ownership.
        pytest.param(True, False, False, True, id="v3_zero_batches_starts_post_import_workflow"),
        # V3 with batches: the load consumer starts data-import-post-import; starting it here
        # too would race the consumer's load.
        pytest.param(True, True, False, False, id="v3_with_batches_leaves_trigger_to_consumer"),
        # Externally managed schemas never ran the post-import steps; the finally-block
        # trigger must not give them a fan-out.
        pytest.param(False, False, True, False, id="externally_managed_schema_gets_no_post_import"),
    ],
)
async def test_post_import_fork(
    is_v3: bool,
    consumer_manages_job_status: bool,
    skip_post_import_activities: bool,
    expect_post_import_child: bool,
):
    executed, child_ids = await _run_workflow(
        is_v3=is_v3,
        consumer_manages_job_status=consumer_manages_job_status,
        skip_post_import_activities=skip_post_import_activities,
    )

    # The load-dependent steps never run inline in new executions — data-import-post-import
    # is their only home (the inline path survives solely for pre-patch replay).
    started = {prefix for prefix in LOAD_DEPENDENT_CHILD_PREFIXES if any(c.startswith(prefix) for c in child_ids)}
    assert started == set()
    assert "calculate_table_size_activity" not in executed

    post_import_marker = f"child:data-import-post-import-{_JOB_ID}"
    if expect_post_import_child:
        # Must start after the COMPLETED write: the resolve activity skips every step
        # for a non-completed job, so the reverse order silently loses them all.
        assert executed.index("update_external_data_job_model") < executed.index(post_import_marker)
    else:
        assert post_import_marker not in executed

    if not skip_post_import_activities:
        # The person-property sync child reads extraction-staged chunks, not the loaded
        # table, so it must keep starting from the workflow on every path.
        assert any(c.startswith("sync-warehouse-person-properties-") for c in child_ids)
        # Steps that don't read the loaded table stay inline.
        assert "create_source_templates" in executed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "steps_mode",
    [
        # New runs dispatch from the step list the resolve activity recorded.
        pytest.param("activity", id="activity_step_list"),
        # In-flight pre-deploy runs have a context without `steps`; the legacy fallback
        # must reproduce the old command sequence or their replay breaks on deploy.
        pytest.param("legacy", id="legacy_fallback"),
    ],
)
@pytest.mark.parametrize(
    "gates_on",
    [
        pytest.param(True, id="all_steps_gated_on"),
        pytest.param(False, id="gated_steps_skipped"),
    ],
)
async def test_post_import_workflow_runs_moved_steps(gates_on: bool, steps_mode: str):
    # If a step is dropped from the registry, V3 syncs silently lose it (there is no
    # other place it runs); if the gates are ignored, disabled products run. Both
    # dispatch paths must issue the same commands for the same gating.
    from products.warehouse_sources.backend.temporal.data_imports.post_import_job import (
        DUCKLAKE_COPY_STEP,
        EMIT_SIGNALS_STEP,
        SEMANTIC_ENRICHMENT_STEP,
        TABLE_SIZE_STEP,
        TABLE_STATISTICS_STEP,
        PostImportContext,
        PostImportWorkflow,
        PostImportWorkflowInputs,
    )

    executed: list[str] = []

    gated_steps = [EMIT_SIGNALS_STEP, SEMANTIC_ENRICHMENT_STEP, TABLE_STATISTICS_STEP] if gates_on else []
    steps = None if steps_mode == "legacy" else [*gated_steps, TABLE_SIZE_STEP, DUCKLAKE_COPY_STEP]

    @activity.defn(name="resolve_post_import_context_activity")
    async def resolve_context(inputs: PostImportWorkflowInputs) -> PostImportContext:
        return PostImportContext(
            source_type="Stripe",
            schema_name="Customer",
            last_synced_at="2026-07-01T00:00:00+00:00",
            emit_signals_enabled=gates_on,
            enrichment_needed=gates_on,
            statistics_needed=gates_on,
            steps=steps,
        )

    @activity.defn(name="calculate_table_size_activity")
    async def calculate_table_size(inputs: CalculateTableSizeActivityInputs) -> None:
        executed.append("calculate_table_size_activity")

    with mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.post_import_job.workflow.start_child_workflow",
        new_callable=mock.AsyncMock,
    ) as mock_start_child:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="test-post-import-workflow",
                workflows=[PostImportWorkflow],
                activities=[resolve_context, calculate_table_size],
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=10),
            ):
                await env.client.execute_workflow(
                    PostImportWorkflow.run,
                    PostImportWorkflowInputs(
                        team_id=1,
                        job_id=_JOB_ID,
                        schema_id=str(uuid.uuid4()),
                        source_id=str(uuid.uuid4()),
                    ),
                    id=str(uuid.uuid4()),
                    task_queue="test-post-import-workflow",
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    child_ids = [call.kwargs["id"] for call in mock_start_child.call_args_list]
    gated_prefixes = (
        "emit-data-import-signals-",
        "enrich-warehouse-table-semantics-",
        "compute-warehouse-table-statistics-",
    )
    started = {prefix for prefix in gated_prefixes if any(c.startswith(prefix) for c in child_ids)}
    assert started == (set(gated_prefixes) if gates_on else set())

    # Table size and the DuckLake copy run for every completed V3 import.
    assert executed == ["calculate_table_size_activity"]
    assert any(c.startswith("ducklake-copy-data-imports-") for c in child_ids)


@pytest.fixture
def _no_close_old_connections():
    # The activity reconnects stale worker connections; under pytest-django that would
    # close the test transaction's connection mid-test.
    with mock.patch("products.warehouse_sources.backend.temporal.data_imports.post_import_job.close_old_connections"):
        yield


def _create_job(team, *, status, schema_snapshot, schema_last_synced_at):
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

    source = ExternalDataSource.objects.create(team=team, source_type="Stripe")
    schema = ExternalDataSchema.objects.create(
        team=team, name="Customer", source=source, last_synced_at=schema_last_synced_at
    )
    job = ExternalDataJob.objects.create(
        team=team,
        pipeline=source,
        schema=schema,
        status=status,
        schema_snapshot=schema_snapshot,
        rows_synced=0,
    )
    return source, schema, job


@pytest.mark.django_db
def test_resolve_context_uses_pre_sync_watermark_from_snapshot(team, _no_close_old_connections):
    # By the time the post-import workflow runs, post-load bookkeeping has already advanced
    # schema.last_synced_at to this sync. Reading the live value instead of the job's
    # creation-time snapshot would filter the entire sync window out of signal emission.
    from datetime import UTC, datetime

    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
    from products.warehouse_sources.backend.temporal.data_imports.post_import_job import (
        DUCKLAKE_COPY_STEP,
        TABLE_SIZE_STEP,
        PostImportWorkflowInputs,
        resolve_post_import_context_activity,
    )

    pre_sync = "2026-07-01T00:00:00+00:00"
    source, schema, job = _create_job(
        team,
        status=ExternalDataJob.Status.COMPLETED,
        schema_snapshot={"last_synced_at": pre_sync},
        schema_last_synced_at=datetime(2026, 7, 30, tzinfo=UTC),
    )

    ctx = resolve_post_import_context_activity(
        PostImportWorkflowInputs(
            team_id=team.pk, job_id=str(job.id), schema_id=str(schema.id), source_id=str(source.id)
        )
    )

    assert ctx.source_type == "Stripe"
    assert ctx.schema_name == "Customer"
    assert ctx.last_synced_at == pre_sync
    # The always-on steps must be recorded for a completed job (feature-gated steps are
    # off in the test environment); a None here would send new runs down the legacy path.
    assert ctx.steps is not None
    assert ctx.steps[-2:] == [TABLE_SIZE_STEP, DUCKLAKE_COPY_STEP]


@pytest.mark.django_db
@pytest.mark.parametrize("case", ["job_deleted", "job_not_completed"])
def test_resolve_context_skips_all_steps_when_job_is_gone_or_not_completed(team, case, _no_close_old_connections):
    # A cancelled job (Completed write suppressed after the final batch) or a deleted job
    # must not fan out any step — steps=[] rather than None, or the workflow's legacy
    # fallback would still run table size and the DuckLake copy for it.
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
    from products.warehouse_sources.backend.temporal.data_imports.post_import_job import (
        PostImportContext,
        PostImportWorkflowInputs,
        resolve_post_import_context_activity,
    )

    source, schema, job = _create_job(
        team,
        status=ExternalDataJob.Status.FAILED if case == "job_not_completed" else ExternalDataJob.Status.COMPLETED,
        schema_snapshot={"last_synced_at": "2026-07-01T00:00:00+00:00"},
        schema_last_synced_at=None,
    )
    job_id = str(uuid.uuid4()) if case == "job_deleted" else str(job.id)

    ctx = resolve_post_import_context_activity(
        PostImportWorkflowInputs(team_id=team.pk, job_id=job_id, schema_id=str(schema.id), source_id=str(source.id))
    )

    assert ctx == PostImportContext(steps=[])
