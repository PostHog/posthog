import uuid
import asyncio
import datetime as dt
import dataclasses
from typing import Any, NoReturn, Optional

from django.db.models import Prefetch

from structlog.contextvars import bind_contextvars
from structlog.typing import FilteringBoundLogger
from temporalio import activity

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.activity_context import current_activity_attempt
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.shutdown import ShutdownMonitor

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    apply_incremental_lookback,
    process_incremental_value,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.metrics import TERMINAL_JOB_STATUSES
from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.extract import (
    handle_non_retryable_error,
    report_heartbeat_timeout,
    trim_source_job_inputs,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.pipeline import (
    PipelineNonDLT,
    PipelineResult,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import PipelineInputs
from products.warehouse_sources.backend.temporal.data_imports.row_tracking import setup_row_tracking
from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ResumableSource, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_context import bind_job_context
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    RowFilterValidationError,
    validate_and_coerce_row_filters,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.exceptions import CDCHandledExternally
from products.warehouse_sources.backend.types import ExternalDataSourceType

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class ImportDataActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    source_id: uuid.UUID
    run_id: str
    reset_pipeline: Optional[bool] = None

    @property
    def properties_to_log(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "schema_id": self.schema_id,
            "source_id": self.source_id,
            "run_id": self.run_id,
            "reset_pipeline": self.reset_pipeline,
        }


@database_sync_to_async_pool
def _get_external_data_job(run_id: str) -> ExternalDataJob:
    return ExternalDataJob.objects.prefetch_related(
        "pipeline", Prefetch("schema", queryset=ExternalDataSchema.objects.prefetch_related("source"))
    ).get(id=run_id)


@database_sync_to_async_pool
def _get_external_data_schema(schema_id: uuid.UUID, team_id: int) -> ExternalDataSchema:
    return (
        ExternalDataSchema.objects.prefetch_related("source", "table")
        .exclude(deleted=True)
        .get(id=schema_id, team_id=team_id)
    )


@activity.defn
async def import_data_activity_sync(inputs: ImportDataActivityInputs) -> PipelineResult:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    tag_queries(team_id=inputs.team_id, product=Product.WAREHOUSE, feature=Feature.IMPORT_PIPELINE)

    await asyncio.to_thread(report_heartbeat_timeout, inputs, logger)

    async with Heartbeater(factor=30), ShutdownMonitor() as shutdown_monitor:
        await setup_row_tracking(inputs.team_id, inputs.schema_id)

        model = await _get_external_data_job(inputs.run_id)

        if model.pipeline_version == ExternalDataJob.PipelineVersion.V3:
            attempt = current_activity_attempt()
            if attempt > 1 and model.status in TERMINAL_JOB_STATUSES:
                await logger.ainfo(
                    "Skipping retry - job already terminal",
                    status=model.status,
                    attempt=attempt,
                )
                return PipelineResult(
                    should_trigger_cdp_producer=False,
                    consumer_manages_job_status=True,
                )

        await logger.adebug("Running import_data_activity")

        source_type = ExternalDataSourceType(model.pipeline.source_type)

        bind_job_context(
            team_id=inputs.team_id,
            source_type=str(source_type),
            external_data_source_id=inputs.source_id,
            external_data_schema_id=inputs.schema_id,
            external_data_job_id=inputs.run_id,
        )

        job_inputs = PipelineInputs(
            source_id=inputs.source_id,
            schema_id=inputs.schema_id,
            run_id=inputs.run_id,
            team_id=inputs.team_id,
            job_type=source_type,
            dataset_name=await database_sync_to_async_pool(model.folder_path)(),
        )

        await trim_source_job_inputs(model.pipeline)

        schema: ExternalDataSchema | None = model.schema
        assert schema is not None

        if inputs.reset_pipeline is not None:
            reset_pipeline = inputs.reset_pipeline
        else:
            reset_pipeline = schema.sync_type_config.get("reset_pipeline", False) is True

        await logger.adebug(f"schema.sync_type_config = {schema.sync_type_config}")
        await logger.adebug(f"reset_pipeline = {reset_pipeline}")

        schema = await _get_external_data_schema(inputs.schema_id, inputs.team_id)

        processed_incremental_last_value = None
        processed_incremental_earliest_value = None

        if reset_pipeline is not True:
            processed_incremental_last_value = process_incremental_value(
                schema.sync_type_config.get("incremental_field_last_value"),
                schema.sync_type_config.get("incremental_field_type"),
            )
            processed_incremental_earliest_value = process_incremental_value(
                schema.incremental_field_earliest_value,
                schema.incremental_field_type,
            )

            # Shift the watermark back by the user-configured lookback for the source query only
            # (the stored watermark is untouched), so each incremental run re-reads a rolling
            # overlap window and catches late or backdated rows. Incremental merge makes the
            # re-read idempotent — append would duplicate, so it's gated to incremental.
            if schema.is_incremental:
                processed_incremental_last_value = apply_incremental_lookback(
                    processed_incremental_last_value,
                    schema.incremental_field_type,
                    schema.incremental_field_lookback_seconds,
                )

        if schema.should_use_incremental_field:
            await logger.adebug(f"Incremental last value being used is: {processed_incremental_last_value}")

        if processed_incremental_earliest_value:
            await logger.adebug(f"Incremental earliest value being used is: {processed_incremental_earliest_value}")

        # Re-validate against current metadata so a stale filter (dropped column, changed type)
        # fails here with an actionable message rather than emitting a broken query downstream.
        try:
            row_filters = validate_and_coerce_row_filters(schema.row_filters, schema.schema_metadata)
        except RowFilterValidationError as e:
            raise RowFilterValidationError(
                f"Row filter on schema '{schema.name}' no longer matches the current table schema ({e}). "
                f"Fix or remove the row filter in the schema's configuration to resume syncing."
            ) from e

        if SourceRegistry.is_registered(source_type):
            source_inputs = SourceInputs(
                schema_name=schema.name,
                schema_id=str(schema.id),
                source_id=str(inputs.source_id),
                team_id=inputs.team_id,
                should_use_incremental_field=schema.should_use_incremental_field,
                incremental_field=schema.incremental_field if schema.should_use_incremental_field else None,
                incremental_field_type=schema.incremental_field_type if schema.should_use_incremental_field else None,
                db_incremental_field_last_value=processed_incremental_last_value
                if schema.should_use_incremental_field
                else None,
                db_incremental_field_earliest_value=processed_incremental_earliest_value
                if schema.should_use_incremental_field
                else None,
                logger=logger,
                job_id=inputs.run_id,
                reset_pipeline=reset_pipeline,
                enabled_columns=schema.enabled_columns,
                row_filters=row_filters,
                schema_metadata=schema.schema_metadata,
                s3_folder_name=schema.resolved_s3_folder_name,
            )

            new_source = SourceRegistry.get_source(source_type)

            try:
                config = new_source.parse_config(model.pipeline.job_inputs)
            except Exception as e:
                # A stored config that can't be parsed (corrupt or double-encoded `job_inputs`)
                # fails identically on every attempt — there is nothing to retry. Treat it as
                # non-retryable so the job gives up cleanly instead of crash-looping and spamming
                # error tracking. Mirrors the skip in `sync_new_schemas_activity`.
                await handle_non_retryable_error(job_inputs, str(e), logger, e)

            resumable_source_manager: ResumableSourceManager | None = None
            try:
                if isinstance(new_source, ResumableSource):
                    resumable_source_manager = new_source.get_resumable_source_manager(source_inputs)
                    source_response = await database_sync_to_async_pool(new_source.source_for_pipeline)(
                        config, resumable_source_manager, source_inputs
                    )
                elif isinstance(new_source, SimpleSource):
                    source_response = await database_sync_to_async_pool(new_source.source_for_pipeline)(
                        config, source_inputs
                    )
                else:
                    raise TypeError(
                        f"{new_source.__class__.__name__} does not implement either SimpleSource or ResumableSource"
                    )
            except CDCHandledExternally:
                await logger.ainfo("Schema is in CDC streaming mode — handled by CDCExtractionWorkflow, skipping")

                await database_sync_to_async_pool(ExternalDataJob.objects.filter(id=job_inputs.run_id).update)(
                    billable=False, status=ExternalDataJob.Status.COMPLETED, finished_at=dt.datetime.now(dt.UTC)
                )

                # Pause the per-schema schedule — CDCExtractionWorkflow handles this
                # schema now. The schedule is unpaused if the schema transitions back
                # to snapshot mode (e.g., after a TRUNCATE or re-enable after grace period).
                try:
                    from products.data_warehouse.backend.facade.api import pause_external_data_schedule

                    await database_sync_to_async_pool(pause_external_data_schedule)(str(inputs.schema_id))
                    await logger.ainfo("Paused per-schema schedule for CDC streaming schema")
                except Exception:
                    await logger.awarning("Failed to pause per-schema schedule for CDC streaming schema")

                return PipelineResult(
                    should_trigger_cdp_producer=False,
                    consumer_manages_job_status=True,
                    skip_post_import_activities=True,
                )
            except Exception as e:
                # Some sources connect to the remote during setup rather than lazily during
                # the run — e.g. for a `mongodb+srv://` URI pymongo resolves the SRV DNS
                # record inside the MongoClient constructor. A non-retryable error raised
                # here (deleted/misconfigured cluster hostname, revoked credentials) would
                # otherwise bypass the guard in `_run` and be retried up to the activity's
                # maximum on every scheduled sync. Route it through the same policy.
                await _handle_import_error(job_inputs, logger, e)

            return await _run(
                job_inputs=job_inputs,
                source_response=source_response,
                logger=logger,
                reset_pipeline=reset_pipeline,
                shutdown_monitor=shutdown_monitor,
                resumable_source_manager=resumable_source_manager,
            )
        else:
            raise ValueError(f"Source type {model.pipeline.source_type} not supported")


@database_sync_to_async_pool
def _get_models(
    job_id: str,
) -> tuple[ExternalDataJob, ExternalDataSchema, ExternalDataSource, DataWarehouseTable | None]:
    job = ExternalDataJob.objects.select_related("schema", "schema__table").get(id=job_id)
    schema: ExternalDataSchema | None = job.schema
    source: ExternalDataSource | None = job.pipeline
    if schema is None:
        raise Exception("No schema attached to job")
    if source is None:
        raise Exception("No source attached to job")

    table: DataWarehouseTable | None = schema.table
    return job, schema, source, table


async def _handle_import_error(
    job_inputs: PipelineInputs,
    logger: FilteringBoundLogger,
    error: Exception,
) -> NoReturn:
    """Route an import error through the source's non-retryable error policy.

    Errors the source classifies as non-retryable (bad credentials, a deleted or
    misconfigured remote — e.g. a MongoDB ``mongodb+srv://`` hostname whose DNS record no
    longer resolves) are handed to ``handle_non_retryable_error``, which stops the job after
    a few attempts instead of retrying up to the activity's maximum. Errors the source classifies
    as expected transient failures (e.g. a persistent upstream 5xx) are re-raised for Temporal to
    retry but logged at warning level so they don't open a fresh error-tracking issue each attempt.
    Everything else is logged as an unhandled exception and re-raised so Temporal retries it as usual.
    """
    source_cls = SourceRegistry.get_source(job_inputs.job_type)
    non_retryable_errors = source_cls.get_non_retryable_errors()
    error_msg = str(error)
    is_non_retryable_error = any(
        non_retryable_error in error_msg for non_retryable_error in non_retryable_errors.keys()
    )
    if is_non_retryable_error:
        await handle_non_retryable_error(job_inputs, error_msg, logger, error)
    elif any(transient_error in error_msg for transient_error in source_cls.get_expected_transient_errors()):
        # Expected upstream flakiness (e.g. a persistent 5xx from the source's API). Temporal
        # retries the activity, so log at warning level instead of raising a new error-tracking
        # issue on every retry.
        await logger.awarning(f"Expected transient error during import_data_activity, retrying: {error_msg}")
        raise error
    else:
        await logger.aexception(error_msg)
        await logger.adebug("Error encountered during import_data_activity - re-raising")
        raise error


async def _run(
    job_inputs: PipelineInputs,
    source_response: SourceResponse,
    logger: FilteringBoundLogger,
    reset_pipeline: bool,
    shutdown_monitor: ShutdownMonitor,
    resumable_source_manager: ResumableSourceManager | None,
) -> PipelineResult:
    try:
        job, schema, source, table = await _get_models(job_inputs.run_id)

        use_v3 = job.pipeline_version == ExternalDataJob.PipelineVersion.V3

        if use_v3:
            from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3 import PipelineV3

            logger.info("Running V3 pipeline (feature flag enabled)")
            pipeline: PipelineV3 | PipelineNonDLT = PipelineV3(
                source_response,
                logger,
                job_inputs.run_id,
                reset_pipeline,
                shutdown_monitor,
                job,
                schema,
                source,
                table,
                resumable_source_manager,
            )
        else:
            pipeline = PipelineNonDLT(
                source_response,
                logger,
                job_inputs.run_id,
                reset_pipeline,
                shutdown_monitor,
                job,
                schema,
                source,
                table,
                resumable_source_manager,
            )

        result = await pipeline.run()
        del pipeline
        await logger.adebug("Finished running pipeline")
        return result
    except Exception as e:
        await _handle_import_error(job_inputs, logger, e)
