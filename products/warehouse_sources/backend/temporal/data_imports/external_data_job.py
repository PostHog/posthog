import re
import json
import typing
import datetime as dt
import dataclasses

from django.conf import settings

import posthoganalytics
from structlog.contextvars import bind_contextvars
from temporalio import activity, exceptions, workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.workflow import ParentClosePolicy, start_child_workflow

# TODO: remove dependency
from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.schedule import trigger_schedule_buffer_one
from posthog.temporal.ducklake.ducklake_copy_data_imports_workflow import (
    DataImportsDuckLakeCopyInputs,
    DuckLakeCopyDataImportsWorkflow,
)
from posthog.temporal.utils import CDPProducerWorkflowInputs, ExternalDataWorkflowInputs
from posthog.utils import get_machine_id

from products.data_warehouse.backend.facade.api import (
    a_unpause_external_data_schedule,
    create_warehouse_templates_for_source,
    update_external_job_status,
)
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema, update_should_sync
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import EmitSignalsActivityInputs
from products.warehouse_sources.backend.temporal.data_imports.metrics import get_data_import_finished_metric
from products.warehouse_sources.backend.temporal.data_imports.row_tracking import finish_row_tracking, get_rows
from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock import (
    AcquireV3LockActivityInputs,
    CheckPipelineVersionActivityInputs,
    ReleaseV3LockActivityInputs,
    acquire_v3_pipeline_lock_activity,
    check_pipeline_version_activity,
    release_v3_pipeline_lock_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.calculate_table_size import (
    CalculateTableSizeActivityInputs,
    calculate_table_size_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.check_billing_limits import (
    CheckBillingLimitsActivityInputs,
    check_billing_limits_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.compute_table_statistics import (
    ComputeTableStatisticsInputs,
    ComputeTableStatisticsWorkflow,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    CreateExternalDataJobModelActivityInputs,
    create_external_data_job_model_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.enrich_table_semantics import (
    EnrichTableSemanticsInputs,
    EnrichTableSemanticsWorkflow,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportDataActivityInputs,
    import_data_activity_sync,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.repartition_table import (
    RepartitionActivityInputs,
    maybe_repartition_table_activity,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

LOGGER = get_logger(__name__)

# Cap retries at 3 in local dev so failing syncs don't loop for tens of minutes while developers
# iterate; prod cadence is unchanged. Defined at module level so tests can patch them to keep the
# expensive retry-exhaustion paths fast.
MAX_RESUMABLE_SOURCE_RETRIES = 3 if settings.DEBUG else 15
MAX_INCREMENTAL_SOURCE_RETRIES = 3 if settings.DEBUG else 9

Any_Source_Errors: dict[str, str | None] = {
    "Could not establish session to SSH gateway": None,
    # Raised by `SSHTunnel.get_tunnel` when `is_auth_valid()` fails — the SSH tunnel private key
    # can't be parsed, or password auth is missing a username/password. Shared by every
    # SSH-capable source (Postgres, Redshift, MySQL, MSSQL, ClickHouse). The auth config is fixed,
    # so retrying just replays the same invalid credentials; stop and tell the customer to fix it.
    "SSHTunnel auth is not valid": (
        "Your SSH tunnel credentials are not valid. Check the SSH authentication details "
        "(private key, passphrase, or username and password) on the source's SSH tunnel "
        "configuration, then re-enable the sync."
    ),
    "Primary key required for incremental syncs": None,
    "The primary keys for this table are not unique": None,
    "Integration matching query does not exist": "The connected account for this source is no longer available — it may have been disconnected. Please reconnect the source's account.",
    # A fatal TLS alert from the remote host (raised in the shared HTTP transport for every
    # REST-based source). The server refused the handshake, which is deterministic for a given
    # host/TLS config — retrying replays the identical failure, so it's not transient. Usually a
    # misconfigured or wrong host/URL on the customer's side. Match the stable alert name, not the
    # volatile `_ssl.c:NNNN` suffix or per-request host.
    "SSLV3_ALERT_HANDSHAKE_FAILURE": "Could not complete a secure (TLS) connection to the source's server — the handshake was rejected. Please check the configured host/URL is correct and that the server supports a compatible TLS version.",
    # Raised by WebhookSourceManager — keep the key byte-equal to
    # `WEBHOOK_DELIVERY_FAILING_ERROR` in sources/common/webhook_s3.py.
    "Webhook delivery is failing": (
        "Your webhook is failing to deliver — PostHog rejected recent deliveries. "
        "Check your signing secret and webhook configuration in the source settings, "
        "then re-enable syncing."
    ),
}


@dataclasses.dataclass
class UpdateExternalDataJobStatusInputs:
    team_id: int
    job_id: str | None
    schema_id: str
    source_id: str
    status: str
    internal_error: str | None
    latest_error: str | None

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "job_id": self.job_id,
            "schema_id": self.schema_id,
            "source_id": self.source_id,
            "status": self.status,
        }


@activity.defn
async def update_external_data_job_model(inputs: UpdateExternalDataJobStatusInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    rows_tracked = await get_rows(inputs.team_id, inputs.schema_id)
    if rows_tracked > 0 and inputs.status == ExternalDataJob.Status.COMPLETED:
        msg = f"Rows tracked is greater than 0 on a COMPLETED job. rows_tracked={rows_tracked}"
        logger.debug(msg)
        capture_exception(Exception(msg))

    await finish_row_tracking(inputs.team_id, inputs.schema_id)

    if inputs.job_id is None:
        job: ExternalDataJob | None = await database_sync_to_async_pool(
            lambda: (
                ExternalDataJob.objects.filter(schema_id=inputs.schema_id, status=ExternalDataJob.Status.RUNNING)
                .order_by("-created_at")
                .first()
            )
        )()
        if job is None:
            logger.info("No job to update status on")
            return

        job_id = str(job.pk)
    else:
        job_id = inputs.job_id

    if inputs.internal_error:
        logger.exception(
            f"External data job failed for external data schema {inputs.schema_id} on job {inputs.job_id} with error: {inputs.internal_error}"
        )

        internal_error_normalized = re.sub("[\n\r\t]", " ", inputs.internal_error)

        source: ExternalDataSource = await database_sync_to_async_pool(ExternalDataSource.objects.get)(
            pk=inputs.source_id
        )
        source_cls = SourceRegistry.get_source(ExternalDataSourceType(source.source_type))
        non_retryable_errors = source_cls.get_non_retryable_errors()

        if len(non_retryable_errors) == 0:
            non_retryable_errors = Any_Source_Errors
        else:
            non_retryable_errors = {**Any_Source_Errors, **non_retryable_errors}

        has_non_retryable_error = any(error in internal_error_normalized for error in non_retryable_errors.keys())
        if has_non_retryable_error:
            posthoganalytics.capture(
                distinct_id=get_machine_id(),
                event="schema non-retryable error",
                properties={
                    "schemaId": inputs.schema_id,
                    "sourceId": inputs.source_id,
                    "sourceType": source.source_type,
                    "jobId": inputs.job_id,
                    "teamId": inputs.team_id,
                    "error": inputs.internal_error,
                },
            )
            await database_sync_to_async_pool(update_should_sync)(
                schema_id=inputs.schema_id, team_id=inputs.team_id, should_sync=False
            )

            friendly_errors = [
                friendly_error
                for error, friendly_error in non_retryable_errors.items()
                if error in internal_error_normalized
            ]

            if friendly_errors and friendly_errors[0] is not None:
                logger.exception(friendly_errors[0])
                inputs.latest_error = friendly_errors[0]

    await database_sync_to_async_pool(update_external_job_status)(
        job_id=job_id,
        status=ExternalDataJob.Status(inputs.status),
        latest_error=inputs.latest_error,
        logger=logger,
        team_id=inputs.team_id,
    )

    logger.info(
        f"Updated external data job with for external data source {job_id} to status {inputs.status}",
    )

    # If an admin action paused the schedule before triggering this run, auto-
    # unpause it on COMPLETED so support ops don't have to remember. On any
    # non-COMPLETED outcome (FAILED, BILLING_LIMIT_REACHED, …) the flag stays
    # set and the schedule stays paused — a human looks at it before resuming.
    if inputs.status == ExternalDataJob.Status.COMPLETED:
        await _maybe_unpause_schedule_after_admin_run(inputs.schema_id, logger)


async def _maybe_unpause_schedule_after_admin_run(schema_id: str, logger) -> None:
    try:
        schema = await database_sync_to_async_pool(ExternalDataSchema.objects.get)(id=schema_id)
    except ExternalDataSchema.DoesNotExist:
        return

    sync_type_config = schema.sync_type_config or {}
    if not sync_type_config.get("admin_unpause_schedule_after_run"):
        return

    try:
        await a_unpause_external_data_schedule(schema_id)
    except Exception:
        logger.exception(f"Failed to auto-unpause schedule for schema {schema_id} after admin run")
        return

    sync_type_config.pop("admin_unpause_schedule_after_run", None)
    schema.sync_type_config = sync_type_config
    await database_sync_to_async_pool(schema.save)(update_fields=["sync_type_config"])
    logger.info(f"Auto-unpaused schedule for schema {schema_id} after successful admin-triggered run")


@dataclasses.dataclass
class CreateSourceTemplateInputs:
    team_id: int
    run_id: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "run_id": self.run_id,
        }


@activity.defn
def create_source_templates(inputs: CreateSourceTemplateInputs) -> None:
    create_warehouse_templates_for_source(team_id=inputs.team_id, run_id=inputs.run_id)


@activity.defn
def trigger_schedule_buffer_one_activity(schedule_id: str) -> None:
    schema = ExternalDataSchema.objects.get(id=schedule_id)
    logger = LOGGER.bind(team_id=schema.team.pk)

    logger.debug(f"Triggering temporal schedule {schedule_id} with policy 'buffer one'")

    temporal = sync_connect()
    trigger_schedule_buffer_one(temporal, schedule_id)


# TODO: update retry policies
@workflow.defn(name="external-data-job")
class ExternalDataJobWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExternalDataWorkflowInputs:
        loaded = json.loads(inputs[0])
        return ExternalDataWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: ExternalDataWorkflowInputs):
        assert inputs.external_data_schema_id is not None

        update_inputs = UpdateExternalDataJobStatusInputs(
            job_id=None,
            status=ExternalDataJob.Status.COMPLETED,
            latest_error=None,
            internal_error=None,
            team_id=inputs.team_id,
            schema_id=str(inputs.external_data_schema_id),
            source_id=str(inputs.external_data_source_id),
        )

        source_type = None
        consumer_manages_job_status = False
        is_v3 = False
        lock_token = None

        # Check pipeline version (FF evaluated once here, propagated everywhere)
        try:
            version_result = await workflow.execute_activity(
                check_pipeline_version_activity,
                CheckPipelineVersionActivityInputs(
                    team_id=inputs.team_id,
                    source_id=inputs.external_data_source_id,
                ),
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            is_v3 = version_result.is_v3
        except Exception:
            workflow.logger.warning(
                "Failed to check pipeline version, defaulting to V2",
                extra={"schema_id": str(inputs.external_data_schema_id)},
            )

        # Only acquire lock for V3 pipelines (V2 never enters this block)
        if is_v3:
            lock_result = None
            try:
                lock_result = await workflow.execute_activity(
                    acquire_v3_pipeline_lock_activity,
                    AcquireV3LockActivityInputs(
                        team_id=inputs.team_id,
                        schema_id=inputs.external_data_schema_id,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            except Exception:
                workflow.logger.error(
                    "Failed to acquire V3 pipeline lock, skipping run",
                    extra={"schema_id": str(inputs.external_data_schema_id)},
                )

            if lock_result is None or not lock_result.acquired:
                workflow.logger.info(
                    "V3 pipeline lock not acquired, skipping",
                    extra={"schema_id": str(inputs.external_data_schema_id)},
                )
                return

            lock_token = lock_result.token

        try:
            # create external data job and trigger activity
            create_external_data_job_inputs = CreateExternalDataJobModelActivityInputs(
                team_id=inputs.team_id,
                schema_id=inputs.external_data_schema_id,
                source_id=inputs.external_data_source_id,
                billable=inputs.billable,
                is_v3=is_v3,
            )

            create_job_result = await workflow.execute_activity(
                create_external_data_job_model_activity,
                create_external_data_job_inputs,
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    maximum_attempts=1,
                    non_retryable_error_types=["NotNullViolation", "IntegrityError"],
                ),
            )
            # Safety net, to avoid errors if old workers didn't pick up the dataclass yet and still return tuples
            if isinstance(create_job_result, tuple):
                job_id, incremental_or_append, source_type = create_job_result
                schema_name, last_synced_at, emit_signals_enabled = None, None, False
                enrichment_needed = False
                statistics_needed = False
            else:
                job_id = create_job_result.job_id
                incremental_or_append = create_job_result.incremental_or_append
                source_type = create_job_result.source_type
                schema_name = create_job_result.schema_name
                last_synced_at = create_job_result.last_synced_at
                emit_signals_enabled = create_job_result.emit_signals_enabled
                enrichment_needed = create_job_result.enrichment_needed
                statistics_needed = create_job_result.statistics_needed
            update_inputs.job_id = str(job_id) if job_id is not None else None

            # Check billing limits
            hit_billing_limit = await workflow.execute_activity(
                check_billing_limits_activity,
                CheckBillingLimitsActivityInputs(job_id=job_id, team_id=inputs.team_id),
                start_to_close_timeout=dt.timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=3,
                ),
            )

            if hit_billing_limit:
                update_inputs.status = ExternalDataJob.Status.BILLING_LIMIT_REACHED
                return

            # Pre-extraction, in-place repartition of any table flagged on a prior run. Runs here — sole
            # writer, lock held, before the merge — so the subsequent merge uses the memory-safe layout.
            # A no-op unless a repartition is pending; never fails the sync (errors are swallowed).
            if job_id is not None:
                try:
                    await workflow.execute_activity(
                        maybe_repartition_table_activity,
                        RepartitionActivityInputs(
                            team_id=inputs.team_id,
                            schema_id=str(inputs.external_data_schema_id),
                            job_id=str(job_id),
                            source_id=str(inputs.external_data_source_id),
                        ),
                        start_to_close_timeout=dt.timedelta(hours=6),
                        heartbeat_timeout=dt.timedelta(minutes=5),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                except Exception:
                    workflow.logger.warning(
                        "Repartition activity failed; continuing with sync on existing layout",
                        extra={"schema_id": str(inputs.external_data_schema_id)},
                    )

            job_inputs = ImportDataActivityInputs(
                team_id=inputs.team_id,
                run_id=job_id,
                schema_id=inputs.external_data_schema_id,
                source_id=inputs.external_data_source_id,
                reset_pipeline=inputs.reset_pipeline,
            )

            is_resumable_source = False
            if source_type is not None:
                source = SourceRegistry.get_source(ExternalDataSourceType(source_type))
                is_resumable_source = isinstance(source, ResumableSource)

            max_resumable_attempts = MAX_RESUMABLE_SOURCE_RETRIES
            max_incremental_attempts = MAX_INCREMENTAL_SOURCE_RETRIES

            if is_resumable_source:
                timeout_params = {
                    "start_to_close_timeout": dt.timedelta(weeks=1),
                    "retry_policy": RetryPolicy(
                        maximum_attempts=max_resumable_attempts,
                        non_retryable_error_types=["NonRetryableException"],
                    ),
                }
            elif incremental_or_append:
                timeout_params = {
                    "start_to_close_timeout": dt.timedelta(weeks=1),
                    "retry_policy": RetryPolicy(
                        maximum_attempts=max_incremental_attempts,
                        non_retryable_error_types=["NonRetryableException"],
                    ),
                }
            else:
                timeout_params = {
                    "start_to_close_timeout": dt.timedelta(hours=24),
                    "retry_policy": RetryPolicy(
                        maximum_attempts=3, non_retryable_error_types=["NonRetryableException"]
                    ),
                }

            pipeline_result = await workflow.execute_activity(
                import_data_activity_sync,
                job_inputs,
                heartbeat_timeout=dt.timedelta(minutes=2),
                **timeout_params,
            )  # type: ignore

            consumer_manages_job_status = pipeline_result.get("consumer_manages_job_status", False)
            skip_post_import_activities = pipeline_result.get("skip_post_import_activities", False)

            if pipeline_result.get("should_trigger_cdp_producer", False):
                await start_child_workflow(
                    workflow="dwh-cdp-producer-job",
                    arg=dataclasses.asdict(
                        CDPProducerWorkflowInputs(
                            team_id=inputs.team_id, schema_id=str(inputs.external_data_schema_id), job_id=job_id
                        )
                    ),
                    id=f"dwh-cdp-producer-job-{job_id}",
                    task_queue=str(settings.DATA_WAREHOUSE_CDP_PRODUCER_TASK_QUEUE),
                    parent_close_policy=ParentClosePolicy.ABANDON,
                    retry_policy=RetryPolicy(
                        maximum_attempts=3,
                        non_retryable_error_types=["NondeterminismError"],
                    ),
                )

            if skip_post_import_activities:
                workflow.logger.info(
                    "Skipping post-import activities for externally managed schema",
                    extra={
                        "schema_id": str(inputs.external_data_schema_id),
                        "source_id": str(inputs.external_data_source_id),
                    },
                )
                return

            # Emit signals for new records (if registered for this source type + schema), if FF enabled.
            # Fire-and-forget: runs on its own task queue so it doesn't block the import pipeline.
            if source_type is not None and schema_name is not None and emit_signals_enabled:
                # Started by registered workflow name (not class import) so warehouse_sources
                # doesn't import the signals product, which depends on it. See external_product_hooks.
                await workflow.start_child_workflow(
                    "emit-data-import-signals",
                    EmitSignalsActivityInputs(
                        team_id=inputs.team_id,
                        schema_id=inputs.external_data_schema_id,
                        source_id=inputs.external_data_source_id,
                        job_id=job_id,
                        source_type=source_type,
                        schema_name=schema_name,
                        last_synced_at=last_synced_at,
                    ),
                    id=f"emit-data-import-signals-{job_id}",
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    # TBD: Signals are currently using video export queue as the main one, comment to clarify
                    task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                    # Let the child workflow finish even if the parent completes or fails
                    parent_close_policy=ParentClosePolicy.ABANDON,
                    execution_timeout=dt.timedelta(hours=2),
                )

            # Generate semantic descriptions for the synced table. Gated up front on actual need
            # (feature flag + AI consent AND unannotated columns / missing table description, resolved in
            # create_external_data_job_model_activity) so a steady-state sync — which re-fires every few
            # minutes — doesn't spawn a child that immediately no-ops; the activity re-checks as a safety
            # net and is idempotent. Keyed per schema so only one runs per schema at a time: a concurrent
            # sync gets WorkflowAlreadyStartedError, which we swallow. Fire-and-forget child on the
            # dedicated metadata queue; ABANDON means it never blocks or fails the import.
            if enrichment_needed:
                try:
                    await workflow.start_child_workflow(
                        EnrichTableSemanticsWorkflow.run,
                        EnrichTableSemanticsInputs(
                            team_id=inputs.team_id,
                            schema_id=inputs.external_data_schema_id,
                        ),
                        id=f"enrich-warehouse-table-semantics-{inputs.external_data_schema_id}",
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                        task_queue=settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,
                        parent_close_policy=ParentClosePolicy.ABANDON,
                        execution_timeout=dt.timedelta(minutes=30),
                    )
                except WorkflowAlreadyStartedError:
                    workflow.logger.info(
                        "Semantic enrichment already running for schema, skipping",
                        extra={"schema_id": str(inputs.external_data_schema_id)},
                    )

            # Profile the synced table's columns (null %, min/max, row count) from the Delta log. Gated up
            # front on staleness (feature flag AND stats older than the recompute interval — no data leaves
            # our infra). Keyed per schema so only one runs per schema at a time: a concurrent sync that
            # tries to start a second one gets WorkflowAlreadyStartedError, which we swallow (the running
            # one already covers this schema). The activity itself re-checks recency. Fire-and-forget
            # metadata queue; ABANDON so it never blocks or fails the import.
            if statistics_needed:
                try:
                    await workflow.start_child_workflow(
                        ComputeTableStatisticsWorkflow.run,
                        ComputeTableStatisticsInputs(
                            team_id=inputs.team_id,
                            schema_id=inputs.external_data_schema_id,
                        ),
                        id=f"compute-warehouse-table-statistics-{inputs.external_data_schema_id}",
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                        task_queue=settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,
                        parent_close_policy=ParentClosePolicy.ABANDON,
                        execution_timeout=dt.timedelta(minutes=30),
                    )
                except WorkflowAlreadyStartedError:
                    workflow.logger.info(
                        "Column statistics already running for schema, skipping",
                        extra={"schema_id": str(inputs.external_data_schema_id)},
                    )

            # Create source templates
            await workflow.execute_activity(
                create_source_templates,
                CreateSourceTemplateInputs(team_id=inputs.team_id, run_id=job_id),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            await workflow.execute_activity(
                calculate_table_size_activity,
                CalculateTableSizeActivityInputs(
                    team_id=inputs.team_id, schema_id=str(inputs.external_data_schema_id), job_id=job_id
                ),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            # Start DuckLake copy workflow as a child (fire-and-forget)
            try:
                await workflow.start_child_workflow(
                    DuckLakeCopyDataImportsWorkflow.run,
                    DataImportsDuckLakeCopyInputs(
                        team_id=inputs.team_id,
                        job_id=job_id,
                        schema_ids=[inputs.external_data_schema_id],
                    ),
                    id=f"ducklake-copy-data-imports-{inputs.team_id}-{inputs.external_data_schema_id}",
                    task_queue=settings.DUCKLAKE_TASK_QUEUE,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                )
            except WorkflowAlreadyStartedError:
                workflow.logger.warning(
                    "DuckLake copy already running, skipping",
                    extra={"schema_id": str(inputs.external_data_schema_id)},
                )

        except exceptions.ActivityError as e:
            if isinstance(e.cause, exceptions.ApplicationError) and e.cause.type == "WorkerShuttingDownError":
                # Check if this is a WorkerShuttingDownError - implement Buffer One retry
                schedule_id = str(inputs.external_data_schema_id)
                await workflow.execute_activity(
                    trigger_schedule_buffer_one_activity,
                    schedule_id,
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            elif (
                isinstance(e.cause, exceptions.ApplicationError)
                and e.cause.type == "BillingLimitsWillBeReachedException"
            ):
                # Check if this is a BillingLimitsWillBeReachedException - update the job status
                update_inputs.status = ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW
            elif isinstance(e.cause, exceptions.ApplicationError) and e.cause.type == "NonRetryableException":
                update_inputs.status = ExternalDataJob.Status.FAILED
                update_inputs.internal_error = str(e.cause.cause)
                update_inputs.latest_error = str(e.cause.cause)
                raise
            else:
                # Handle other activity errors normally
                update_inputs.status = ExternalDataJob.Status.FAILED
                update_inputs.internal_error = str(e.cause)
                update_inputs.latest_error = str(e.cause)
                raise
        except Exception as e:
            # Catch all
            update_inputs.internal_error = str(e)
            update_inputs.latest_error = "An unexpected error has ocurred"
            update_inputs.status = ExternalDataJob.Status.FAILED
            raise
        finally:
            # When the consumer manages job status (pipeline v3), skip the COMPLETED
            # update here — the consumer marks the job completed after loading finishes.
            # Still run for FAILED/billing statuses so extraction-phase errors are recorded.
            skip_status_update = (
                consumer_manages_job_status and update_inputs.status == ExternalDataJob.Status.COMPLETED
            )

            get_data_import_finished_metric(source_type=source_type, status=update_inputs.status.lower()).add(1)

            if not skip_status_update:
                await workflow.execute_activity(
                    update_external_data_job_model,
                    update_inputs,
                    start_to_close_timeout=dt.timedelta(minutes=1),
                    retry_policy=RetryPolicy(
                        initial_interval=dt.timedelta(seconds=10),
                        maximum_interval=dt.timedelta(seconds=60),
                        maximum_attempts=0,
                        non_retryable_error_types=["NotNullViolation", "IntegrityError", "DoesNotExist"],
                    ),
                )

            # Release the V3 pipeline lock when the consumer is NOT managing job
            # status (extraction failed before producing batches, or non-V3).
            # When consumer_manages_job_status is True, the consumer releases.
            if is_v3 and lock_token and not consumer_manages_job_status:
                try:
                    await workflow.execute_activity(
                        release_v3_pipeline_lock_activity,
                        ReleaseV3LockActivityInputs(
                            team_id=inputs.team_id,
                            schema_id=inputs.external_data_schema_id,
                            token=lock_token,
                        ),
                        start_to_close_timeout=dt.timedelta(minutes=1),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                except Exception:
                    workflow.logger.warning(
                        "Failed to release V3 pipeline lock in workflow finally block",
                        extra={"schema_id": str(inputs.external_data_schema_id)},
                    )
