from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, NoReturn

from django.conf import settings

import pyarrow as pa
import posthoganalytics
from structlog.typing import FilteringBoundLogger
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_async_client
from posthog.sync import database_sync_to_async_pool

from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.load import get_incremental_field_value
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.cdp_producer import CDPProducer
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.delta_table_helper import (
    DeltaTableHelper,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import (
    BillingLimitsWillBeReachedException,
    DuplicatePrimaryKeysException,
)
from products.warehouse_sources.backend.temporal.data_imports.row_tracking import (
    decrement_rows,
    increment_rows,
    will_hit_billing_limit,
)
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import PipelineInputs
    from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
        ImportDataActivityInputs,
    )


@asynccontextmanager
async def _get_redis():
    """Returns an async Redis client for row tracking operations."""
    redis = None
    try:
        if not settings.DATA_WAREHOUSE_REDIS_HOST or not settings.DATA_WAREHOUSE_REDIS_PORT:
            raise Exception(
                "Missing env vars for dwh row tracking: DATA_WAREHOUSE_REDIS_HOST or DATA_WAREHOUSE_REDIS_PORT"
            )

        redis = get_async_client(f"redis://{settings.DATA_WAREHOUSE_REDIS_HOST}:{settings.DATA_WAREHOUSE_REDIS_PORT}/")
        await redis.ping()
    except Exception as e:
        capture_exception(e)

    yield redis


def build_non_retryable_errors_redis_key(team_id: int, source_id: str, run_id: str) -> str:
    return f"posthog:data_warehouse:non_retryable_errors:{team_id}:{source_id}:{run_id}"


NON_RETRYABLE_ERROR_RETRY_LIMIT = 3


async def trim_source_job_inputs(source: "ExternalDataSource") -> None:
    if not source.job_inputs:
        return

    did_update_inputs = False
    for key, value in source.job_inputs.items():
        if isinstance(value, str):
            if value.startswith(" ") or value.endswith(" "):
                source.job_inputs[key] = value.strip()
                did_update_inputs = True

    if did_update_inputs:
        await database_sync_to_async_pool(source.save)()


def report_heartbeat_timeout(inputs: "ImportDataActivityInputs", logger: FilteringBoundLogger) -> None:
    logger.debug("Checking for heartbeat timeout reporting...")

    try:
        info = activity.info()
        heartbeat_timeout = info.heartbeat_timeout
        current_attempt_scheduled_time = info.current_attempt_scheduled_time

        if not heartbeat_timeout:
            logger.debug(f"No heartbeat timeout set for this activity: {heartbeat_timeout}")
            return

        if not current_attempt_scheduled_time:
            logger.debug(f"No current attempt scheduled time set for this activity: {current_attempt_scheduled_time}")
            return

        if info.attempt < 2:
            logger.debug("First attempt of activity, no heartbeat timeout to report.")
            return

        heartbeat_details = info.heartbeat_details
        if not isinstance(heartbeat_details, tuple | list) or len(heartbeat_details) < 1:
            logger.debug(
                f"No heartbeat details found to analyze for timeout: {heartbeat_details}. Class: {heartbeat_details.__class__.__name__}"
            )
            return

        last_heartbeat = heartbeat_details[-1]
        logger.debug(f"Resuming activity after failure. Last heartbeat details: {last_heartbeat}")

        if not isinstance(last_heartbeat, dict):
            logger.debug(
                f"Last heartbeat details not in expected format (dict). Found: {type(last_heartbeat)}: {last_heartbeat}"
            )
            return

        last_heartbeat_host = last_heartbeat.get("host", None)
        last_heartbeat_timestamp = last_heartbeat.get("ts", None)

        logger.debug(f"Last heartbeat was {last_heartbeat}")

        if last_heartbeat_host is None or last_heartbeat_timestamp is None:
            logger.debug("Incomplete heartbeat details. No host or timestamp found.")
            return

        try:
            last_heartbeat_timestamp = float(last_heartbeat_timestamp)
        except (TypeError, ValueError):
            logger.debug(f"Last heartbeat timestamp could not be converted to float: {last_heartbeat_timestamp}")
            return

        gap_between_beats = current_attempt_scheduled_time.timestamp() - float(last_heartbeat_timestamp)
        if gap_between_beats > heartbeat_timeout.total_seconds():
            logger.debug(
                "Last heartbeat was longer ago than the heartbeat timeout allows. Likely due to a pod OOM or restart.",
                last_heartbeat_host=last_heartbeat_host,
                last_heartbeat_timestamp=last_heartbeat_timestamp,
                gap_between_beats=gap_between_beats,
                heartbeat_timeout_seconds=heartbeat_timeout.total_seconds(),
            )

            posthoganalytics.capture(
                "dwh_pod_heartbeat_timeout",
                distinct_id=None,
                properties={
                    "team_id": inputs.team_id,
                    "schema_id": str(inputs.schema_id),
                    "source_id": str(inputs.source_id),
                    "run_id": inputs.run_id,
                    "host": last_heartbeat_host,
                    "gap_between_beats": gap_between_beats,
                    "heartbeat_timeout_seconds": heartbeat_timeout.total_seconds(),
                    "task_queue": info.task_queue,
                    "workflow_id": info.workflow_id,
                    "workflow_run_id": info.workflow_run_id,
                    "workflow_type": info.workflow_type,
                    "attempt": info.attempt,
                },
            )

            # Durable per-occurrence OOM record for the repartition trigger to read. Best-effort:
            # a write failure here must never disrupt the sync.
            try:
                from products.warehouse_sources.backend.models.oom_event import (  # noqa: PLC0415 — Django models must not be imported at this activity module's load time
                    ExternalDataSchemaOOMEvent,
                )

                if inputs.schema_id is not None:
                    ExternalDataSchemaOOMEvent.objects.for_team(inputs.team_id).create(
                        team_id=inputs.team_id,
                        schema_id=inputs.schema_id,
                        run_id=inputs.run_id,
                        host=last_heartbeat_host,
                        gap_seconds=gap_between_beats,
                    )
            except Exception as record_error:
                logger.debug(f"Failed to record OOM event for schema {inputs.schema_id}: {record_error}")
        else:
            logger.debug("Last heartbeat was within the heartbeat timeout window. No action needed.")
    except Exception as e:
        logger.debug(f"Error while reporting heartbeat timeout: {e}", exc_info=e)


async def handle_non_retryable_error(
    job_inputs: "PipelineInputs",
    error_msg: str,
    logger: FilteringBoundLogger,
    error: Exception,
) -> NoReturn:
    async with _get_redis() as redis_client:
        if redis_client is None:
            await logger.adebug(f"Failed to get Redis client for non-retryable error tracking. error={error_msg}")
            raise NonRetryableException() from error

        retry_key = build_non_retryable_errors_redis_key(
            job_inputs.team_id, str(job_inputs.source_id), job_inputs.run_id
        )
        attempts = await redis_client.incr(retry_key)

        if attempts <= NON_RETRYABLE_ERROR_RETRY_LIMIT:
            await redis_client.expire(retry_key, 86400)  # Expire after 24 hours
            await logger.adebug(
                f"Non-retryable error attempt {attempts}/{NON_RETRYABLE_ERROR_RETRY_LIMIT}, retrying. error={error_msg}"
            )
            raise error

    await logger.adebug(f"Non-retryable error after {attempts} runs, giving up. error={error_msg}")
    raise NonRetryableException() from error


async def reset_rows_synced_if_needed(
    job: "ExternalDataJob",
    is_incremental: bool,
    reset_pipeline: bool,
    should_resume: bool,
) -> None:
    # Reset the rows_synced count - this may not be 0 if the job restarted due to a heartbeat timeout
    if (
        job.rows_synced is not None
        and job.rows_synced != 0
        and (not is_incremental or reset_pipeline is True)
        and not should_resume
    ):
        job.rows_synced = 0
        await database_sync_to_async_pool(job.save)(update_fields=["rows_synced", "updated_at"])


def validate_incremental_sync(
    is_incremental: bool,
    resource: SourceResponse,
) -> None:
    # Check for duplicate primary keys
    if is_incremental and resource.has_duplicate_primary_keys:
        raise DuplicatePrimaryKeysException(
            f"The primary keys for this table are not unique. We can't sync incrementally until the table "
            f"has a unique primary key. Primary keys being used are: {resource.primary_keys}"
        )


async def setup_row_tracking_with_billing_check(
    team_id: int,
    schema: "ExternalDataSchema",
    resource: SourceResponse,
    source: "ExternalDataSource",
    logger: FilteringBoundLogger,
    billable: bool | None = True,
) -> None:
    if resource.rows_to_sync:
        await increment_rows(team_id, schema.id, resource.rows_to_sync)
        # Check billing limits against incoming rows (skip for non-billable jobs)
        if billable and await will_hit_billing_limit(team_id=team_id, source=source, logger=logger):
            raise BillingLimitsWillBeReachedException(
                f"Your account will hit your Data Warehouse billing limits syncing {resource.name} "
                f"with {resource.rows_to_sync} rows"
            )


async def handle_reset_or_full_refresh(
    reset_pipeline: bool,
    should_resume: bool,
    schema: "ExternalDataSchema",
    delta_table_helper: DeltaTableHelper,
    logger: FilteringBoundLogger,
) -> None:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

    if reset_pipeline and not should_resume:
        await logger.adebug("Deleting existing table due to reset_pipeline being set")
        await delta_table_helper.reset_table()
        await database_sync_to_async_pool(schema.update_sync_type_config_for_reset_pipeline)()
    elif schema.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH and not should_resume:
        # Avoid schema mismatches from existing data about to be overwritten
        await logger.adebug("Deleting existing table due to sync being full refresh")
        await delta_table_helper.reset_table()
        await database_sync_to_async_pool(schema.update_sync_type_config_for_reset_pipeline)()


async def handle_corrupted_delta_log(
    schema: "ExternalDataSchema",
    job: "ExternalDataJob",
    delta_table_helper: DeltaTableHelper,
    logger: FilteringBoundLogger,
) -> bool:
    """Detect and revive a Delta table whose `_delta_log` is unreadable, before extraction.

    Interrupted repartition swaps and OOM-crashed merges can leave `_delta_log` inconsistent (open raises
    DeltaError / FileNotFoundError), after which every sync fails to open the table and loops forever.
    Runs before extraction so the table self-heals in the same run:

    - Salvage: an interrupted repartition swap that left a `ready` temp table is finished from temp (no
      re-pull from source).
    - Otherwise the table is reset so this run rebuilds it from source, and the job is marked
      non-billable — the corruption is our fault, not the customer's.

    Returns True if a revive happened. Best-effort: any failure here must not block the sync.
    """
    try:
        if not await delta_table_helper.is_table_corrupted():
            return False
    except Exception as e:
        capture_exception(e)
        return False

    await logger.awarning(
        f"handle_corrupted_delta_log: unreadable delta log detected, reviving schema_id={schema.id}",
        schema_id=str(schema.id),
    )

    # Salvage first: finish an interrupted repartition swap from its `ready` temp table (delete the corrupt
    # live, copy temp into place) rather than re-pull from source. `_resume_swap_with_missing_live` skips
    # and clears the markers when temp is also gone (the terminal corrupt state), so we then fall to reset.
    swap = schema.repartition_swap
    if swap and swap.get("state") == "ready" and swap.get("temp_uri") and swap.get("live_uri"):
        from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.repartition import (  # noqa: PLC0415 — deferred to avoid an import cycle with the repartition modules
            _resume_swap_with_missing_live,
        )
        from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.repartition_table import (  # noqa: PLC0415 — deferred to avoid an import cycle with the repartition modules
            RepartitionTarget,
            _target_from_schema,
        )

        try:
            target = (
                RepartitionTarget.from_dict(schema.repartition_pending)
                if schema.repartition_pending is not None
                else _target_from_schema(schema)
            )
            result = await _resume_swap_with_missing_live(
                helper=delta_table_helper,
                schema=schema,
                target=target,
                temp_uri=swap["temp_uri"],
                live_uri=swap["live_uri"],
                storage_options=delta_table_helper._get_credentials(),
                logger=logger,
            )
            if result.get("outcome") == "completed":
                await logger.ainfo(
                    f"handle_corrupted_delta_log: salvaged from interrupted swap schema_id={schema.id}",
                    schema_id=str(schema.id),
                )
                return True
        except Exception as e:
            capture_exception(e)
            await logger.aexception(f"handle_corrupted_delta_log: salvage failed, resetting: {e}", exc_info=e)

    # Reset + rebuild from source in this run, marked non-billable — we caused the corruption.
    from products.warehouse_sources.backend.models.external_data_schema import (  # noqa: PLC0415 — Django model import kept off this activity module's load path
        update_sync_type_config_keys,
    )

    await delta_table_helper.reset_table()
    await database_sync_to_async_pool(schema.update_sync_type_config_for_reset_pipeline)()
    await database_sync_to_async_pool(update_sync_type_config_keys)(
        schema.id, schema.team_id, removes=["repartition_pending", "repartition_swap"]
    )
    if job.billable:
        job.billable = False
        await database_sync_to_async_pool(job.save)(update_fields=["billable"])

    await logger.awarning(
        f"handle_corrupted_delta_log: reset corrupt table for non-billable rebuild schema_id={schema.id}",
        schema_id=str(schema.id),
    )
    return True


def cleanup_memory(pa_memory_pool: pa.MemoryPool, py_table: pa.Table | None = None) -> None:
    if py_table is not None:
        del py_table
    pa_memory_pool.release_unused()


async def update_incremental_field_values(
    schema: "ExternalDataSchema",
    pa_table: pa.Table,
    resource: SourceResponse,
    last_incremental_field_value: Any,
    earliest_incremental_field_value: Any,
    logger: FilteringBoundLogger,
    log_prefix: str = "",
    staging_run_uuid: str | None = None,
) -> tuple[Any, Any]:
    last_value = get_incremental_field_value(schema, pa_table)

    if last_value is not None:
        if (last_incremental_field_value is None) or (last_value > last_incremental_field_value):
            last_incremental_field_value = last_value

        if resource.sort_mode == "asc":
            await logger.adebug(
                f"{log_prefix}Updating incremental_field_last_value with {last_incremental_field_value}"
            )
            if staging_run_uuid is not None:
                await database_sync_to_async_pool(schema.stage_incremental_field_value)(
                    staging_run_uuid, last_incremental_field_value
                )
            else:
                await database_sync_to_async_pool(schema.update_incremental_field_value)(last_incremental_field_value)

        if resource.sort_mode == "desc":
            earliest_value = get_incremental_field_value(schema, pa_table, aggregate="min")

            if earliest_incremental_field_value is None or earliest_value < earliest_incremental_field_value:
                earliest_incremental_field_value = earliest_value
                await logger.adebug(f"{log_prefix}Updating incremental_field_earliest_value with {earliest_value}")
                if staging_run_uuid is not None:
                    await database_sync_to_async_pool(schema.stage_incremental_field_value)(
                        staging_run_uuid, None, earliest_value
                    )
                else:
                    await database_sync_to_async_pool(schema.update_incremental_field_value)(
                        earliest_value, type="earliest"
                    )

    return last_incremental_field_value, earliest_incremental_field_value


async def update_row_tracking_after_batch(
    job_id: str,
    team_id: int,
    schema_id: Any,
    row_count: int,
    logger: FilteringBoundLogger,
) -> None:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.common.load import update_job_row_count

    await update_job_row_count(job_id, row_count, logger)
    await decrement_rows(team_id, schema_id, row_count)


def should_check_shutdown(
    schema: "ExternalDataSchema",
    resource: SourceResponse,
    reset_pipeline: bool,
    source_is_resumable: bool,
) -> bool:
    # Only raise if we're not running in descending order, otherwise we'll often not
    # complete the job before the incremental value can be updated. Or if the source is
    # resumable
    # TODO: raise when we're within `x` time of the worker being forced to shutdown
    # Raising during a full reset will reset our progress back to 0 rows
    incremental_sync_raise_during_shutdown = (
        schema.should_use_incremental_field and resource.sort_mode != "desc" and not reset_pipeline
    )
    return incremental_sync_raise_during_shutdown or source_is_resumable


async def finalize_desc_sort_incremental_value(
    resource: SourceResponse,
    schema: "ExternalDataSchema",
    last_incremental_field_value: Any,
    logger: FilteringBoundLogger,
    log_prefix: str = "",
    staging_run_uuid: str | None = None,
) -> None:
    if resource.sort_mode == "desc" and last_incremental_field_value is not None:
        await logger.adebug(
            f"{log_prefix}Sort mode is 'desc' -> updating incremental_field_last_value "
            f"with {last_incremental_field_value}"
        )
        await database_sync_to_async_pool(schema.refresh_from_db)()
        if staging_run_uuid is not None:
            await database_sync_to_async_pool(schema.stage_incremental_field_value)(
                staging_run_uuid, last_incremental_field_value
            )
        else:
            await database_sync_to_async_pool(schema.update_incremental_field_value)(last_incremental_field_value)


async def advance_xmin_state(
    resource: SourceResponse,
    schema: "ExternalDataSchema",
    logger: FilteringBoundLogger,
    log_prefix: str = "",
) -> None:
    """Persist the xmin ceiling captured at sync start, once the run's data is durable.

    Persist-then-advance: the ceiling was captured before streaming and is stored only here, at
    completion, so a mid-run crash re-reads the window next time (the upsert on PK is idempotent).
    Deliberately not the per-batch MAX-of-observed advance, which would store the wrong value and is
    wraparound-unsafe for xmin.
    """
    if (
        not schema.is_xmin
        or resource.xmin_ceiling_xid is None
        or resource.xmin_ceiling_xid8 is None
        or resource.xmin_num_wraparound is None
    ):
        return

    await logger.adebug(f"{log_prefix}Advancing xmin cursor to ceiling {resource.xmin_ceiling_xid8}")
    await database_sync_to_async_pool(schema.refresh_from_db)()
    await database_sync_to_async_pool(schema.update_xmin_state)(
        ceiling_xid=resource.xmin_ceiling_xid,
        ceiling_xid8=resource.xmin_ceiling_xid8,
        num_wraparound=resource.xmin_num_wraparound,
    )


async def cdp_producer_clear_chunks(cdp_producer: CDPProducer):
    if await cdp_producer.should_produce_table():
        await cdp_producer.clear_s3_chunks()


async def write_chunk_for_cdp_producer(cdp_producer: CDPProducer, index: int, pa_table: pa.Table):
    if await cdp_producer.should_produce_table():
        await cdp_producer.write_chunk_for_cdp_producer(chunk=index, table=pa_table)


async def run_pre_write_defensive_compact(
    delta_table_helper: DeltaTableHelper,
    schema: "ExternalDataSchema",
    resource: SourceResponse,
    logger: FilteringBoundLogger,
) -> None:
    """Best-effort pre-write compact + vacuum at the start of a sync run.

    Delegates to `DeltaTableHelper.run_maintenance`, which compacts a fragmented Delta
    target (a sync that arrived fragmented because earlier attempts failed before
    reaching `_post_run_operations` — keeping the subsequent per-partition merge scans
    cheap) and otherwise vacuums on a commit-count cadence so a table that OOMs its merge
    every run and never reaches post-load compaction still sheds tombstones (the
    ~99%-dead-file tables). The helper returns the single vacuum watermark to persist, so
    this function is the sole writer of `last_vacuum_version`. Wrapped in try/except so a
    maintenance failure never blocks the actual sync; the original error path is unaffected.

    Used by both `PipelineNonDLT.run` (v2) and `PipelineV3.run` to keep the behaviour
    identical across pipelines without each having to know how to look up `partition_count`
    or how to swallow maintenance errors.
    """
    try:
        from products.warehouse_sources.backend.models.external_data_schema import (  # noqa: PLC0415 — Django model import kept off this activity module's load path
            update_sync_type_config_keys,
        )

        partition_count_for_compact = schema.partition_count or resource.partition_count
        last_vacuum_version = (schema.sync_type_config or {}).get("last_vacuum_version")
        commit_threshold = int(getattr(settings, "DATA_WAREHOUSE_VACUUM_COMMIT_THRESHOLD", 100))
        new_version = await delta_table_helper.run_maintenance(
            partition_count=partition_count_for_compact,
            last_vacuum_version=last_vacuum_version,
            commit_threshold=commit_threshold,
        )
        if new_version is not None and new_version != last_vacuum_version:
            await database_sync_to_async_pool(update_sync_type_config_keys)(
                schema.id, schema.team_id, updates={"last_vacuum_version": new_version}
            )
    except Exception as e:
        capture_exception(e)
        await logger.aexception(f"Pre-write maintenance failed: {e}", exc_info=e)
