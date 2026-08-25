import uuid
import socket
import asyncio
import datetime as dt
import dataclasses
from typing import Any, NoReturn, Optional

from django.db import InterfaceError, OperationalError
from django.db.models import Prefetch

from jsonpath_ng.exceptions import JSONPathError
from requests.exceptions import HTTPError
from structlog.contextvars import bind_contextvars
from structlog.typing import FilteringBoundLogger
from temporalio import activity

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.exceptions_capture import capture_exception
from posthog.integration_secrets.errors import IntegrationSecretsFailure
from posthog.models.integration import UndecryptedIntegrationSecretError
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.activity_context import current_activity_attempt
from posthog.temporal.common.errors import NonReportableError
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.shutdown import ShutdownMonitor

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    apply_incremental_lookback,
    get_schema_if_exists,
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
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    SchemaColumnTypeChangedException,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    is_transient_object_store_error,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition_controller import (
    capture_repartition_event,
    is_repartition_hold_enabled,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.typings import PipelineResult
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_sync import PipelineInputs
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v2.pipeline import PipelineNonDLT
from products.warehouse_sources.backend.temporal.data_imports.row_tracking import setup_row_tracking
from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    AnySource,
    ResumableSource,
    SimpleSource,
    error_message_matches,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.fanout_reuse_flag import (
    is_fanout_warehouse_reuse_enabled,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.history_window import (
    history_start_for_schema,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_context import bind_job_context
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientNonRetryableError,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    RowFilterValidationError,
    validate_and_coerce_row_filters,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.exceptions import CDCHandledExternally
from products.warehouse_sources.backend.temporal.data_imports.util import PostHogInternalDatabaseError
from products.warehouse_sources.backend.temporal.data_imports.workload_report import aworkload_reporting
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


def _parent_unusable_reason(parent: ExternalDataSchema | None) -> str | None:
    """Why a fan-out child can't read this parent from the warehouse, or None when it can."""
    if parent is None:
        return "missing"
    if not parent.should_sync:
        return "disabled"
    if not (parent.is_incremental or parent.sync_type == ExternalDataSchema.SyncType.FULL_REFRESH):
        # An allow-list, not a deny-list: only merge and full-refresh parents hold one row per
        # key. Append accumulates a row per sync, and CDC keeps change history, so the reader —
        # which streams the table as-is, with no dedupe state — would fan the child out once
        # per duplicate. New sync types have to opt in here deliberately.
        return "unsupported_sync_type"
    if not parent.initial_sync_complete:
        return "no_initial_sync"
    return None


async def _warehouse_parent_reuse_available(
    source: AnySource,
    schema: ExternalDataSchema,
    source_id: uuid.UUID,
    team_id: int,
    logger: FilteringBoundLogger,
) -> bool:
    """Whether this run reads its fan-out parents from the warehouse instead of the parent API.

    Reuse is an optimization, never a requirement: any parent the child can't read falls the
    whole run back to the legacy parent-API path, so enabling the flag can't break a schema
    that syncs today. Sources consume the result via `SourceInputs.fanout_warehouse_reuse`;
    this is the single feature-flag evaluation for the run.

    A parent that is mid-sync doesn't force the fallback: `resolve_parent_table_ref` pins the
    read to the parent's last completed snapshot (Delta time travel), so a concurrent rewrite
    can't hand the child a torn table.
    """
    required_parents = source.get_required_parent_schemas(schema.name)
    if not required_parents:
        return False
    if not await database_sync_to_async_pool(is_fanout_warehouse_reuse_enabled)(team_id):
        return False

    for parent_name in required_parents:
        parent = await database_sync_to_async_pool(get_schema_if_exists)(parent_name, team_id, source_id)
        unusable_reason = _parent_unusable_reason(parent)
        if unusable_reason is not None:
            await logger.ainfo(
                "data_imports.fanout_parent_unusable",
                schema=schema.name,
                parent=parent_name,
                reason=unusable_reason,
            )
            return False

    return True


def _import_held_for_repartition(schema: ExternalDataSchema | None, logger: FilteringBoundLogger) -> bool:
    """Whether an in-flight repartition should pause this schema's import for one run.

    Both conditions have to hold: the schema opted into the hold, and a rewrite checkpoint is fresh
    enough to be worth waiting for. The flag is checked second so a schema without it never pays for
    the evaluation, and a flag lookup that throws leaves the import running — pausing a customer's
    ingestion is the more expensive way to be wrong.
    """
    if schema is None or not schema.repartition_holds_import:
        return False
    try:
        if not is_repartition_hold_enabled(schema):
            return False
    except Exception:
        logger.warning("Could not evaluate the repartition hold flag; importing", exc_info=True)
        return False

    rewrite = schema.repartition_rewrite or {}
    logger.info(
        "Holding import: a repartition rewrite is converging on this table",
        schema_id=str(schema.id),
        rows_written=rewrite.get("rows_written"),
        held_at=rewrite.get("held_at"),
    )
    capture_repartition_event(
        "warehouse_repartition_import_held",
        {
            "team_id": schema.team_id,
            "schema_id": str(schema.id),
            "resource_name": schema.name,
            "rows_written": rewrite.get("rows_written"),
            "held_at": rewrite.get("held_at"),
        },
    )
    return True


@activity.defn
async def import_data_activity_sync(inputs: ImportDataActivityInputs) -> PipelineResult:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()
    tag_queries(team_id=inputs.team_id, product=Product.WAREHOUSE, feature=Feature.IMPORT_PIPELINE)

    await asyncio.to_thread(report_heartbeat_timeout, inputs, logger)

    # Async variant: teardown joins the sampler thread and talks to Redis, which must not block
    # this activity's event loop (or its heartbeats).
    async with aworkload_reporting(
        team_id=inputs.team_id,
        schema_id=str(inputs.schema_id),
        run_id=str(inputs.run_id),
        host=socket.gethostname(),
        # Retries share the run_id; the attempt lets the newest reporter own the run key while a
        # zombie predecessor stands down (its heartbeat timed out, but it may still be running).
        attempt=current_activity_attempt(),
    ):
        try:
            return await _import_data_with_reporting(inputs, logger)
        except (OperationalError, InterfaceError, PostHogInternalDatabaseError) as e:
            # The setup phase (resolving the job/schema/source rows for this run) reads PostHog's
            # own app DB through the Django ORM before the source's error handling takes over. A
            # transient connection-pool blip there — a PgBouncer server_login_retry cooldown, the
            # primary briefly in recovery — raises this exception type, which can only mean our own
            # infra, never the customer's source (every source talks to a customer database over a
            # raw driver connection, not the ORM). Re-raise as NonReportableError so Temporal
            # retries the whole activity and it self-heals, rather than failing the sync with the
            # raw driver string as latest_error. _handle_import_error already classifies these types
            # this way once the run is under way; this covers the setup calls that run before it.
            await logger.awarning(str(e))
            raise NonReportableError(str(e)) from e


async def _import_data_with_reporting(inputs: ImportDataActivityInputs, logger: FilteringBoundLogger) -> PipelineResult:
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
                # The consumer already finalized this run (that's how it became terminal), so the
                # workflow must not overwrite the status or release the lock — see PipelineResult.
                return PipelineResult(
                    should_trigger_cdp_producer=False,
                    consumer_manages_job_status=True,
                )

        # A rewrite spanning several activity budgets resumes only while live stays at the Delta
        # version its checkpoint was built against, and the merge below is what moves it. Importing
        # here invalidates the checkpoint the previous run wrote, so the rewrite restarts from row 0
        # and the table never converges. Skipping leaves this run a clean no-op: the workflow
        # finalizes as usual and the next sync picks the data up once the rewrite lands. The hold
        # lapses on its own if the rewrite stops advancing, so a stuck one costs freshness rather
        # than ingestion.
        if await database_sync_to_async_pool(_import_held_for_repartition)(model.schema, logger):
            return PipelineResult(should_trigger_cdp_producer=False, consumer_manages_job_status=False)

        await logger.adebug("Running import_data_activity")

        source_type = ExternalDataSourceType(model.pipeline.source_type)

        bind_job_context(
            team_id=inputs.team_id,
            source_type=str(source_type),
            external_data_source_id=inputs.source_id,
            external_data_schema_id=inputs.schema_id,
            external_data_job_id=inputs.run_id,
            schema_name=model.schema.name if model.schema is not None else None,
            sync_type=model.schema.sync_type if model.schema is not None else None,
            pipeline_version=model.pipeline_version,
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

        try:
            schema = await _get_external_data_schema(inputs.schema_id, inputs.team_id)
        except ExternalDataSchema.DoesNotExist as e:
            await _handle_import_error(job_inputs, logger, e)

        processed_incremental_last_value = None
        processed_incremental_earliest_value = None
        # The cursor as stored, before the lookback shift below moves it back.
        incremental_last_value_before_lookback = None

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
                incremental_last_value_before_lookback = processed_incremental_last_value
                processed_incremental_last_value = apply_incremental_lookback(
                    processed_incremental_last_value,
                    schema.incremental_field_type,
                    schema.incremental_field_lookback_seconds,
                )

        if schema.should_use_incremental_field:
            await logger.adebug(f"Incremental last value being used is: {processed_incremental_last_value}")

        if processed_incremental_earliest_value:
            await logger.adebug(f"Incremental earliest value being used is: {processed_incremental_earliest_value}")

        # None for a source that reads everything, which is most of them.
        history_start = await database_sync_to_async_pool(history_start_for_schema)(schema, inputs.run_id)
        if history_start is not None:
            await logger.adebug(f"History start for this schema is: {history_start}")

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
            new_source = SourceRegistry.get_source(source_type)

            fanout_warehouse_reuse = await _warehouse_parent_reuse_available(
                new_source, schema, inputs.source_id, inputs.team_id, logger
            )
            # INFO so it's visible without DEBUG: confirms which parent-source path a fan-out
            # child took, and doubles as rollout-adoption telemetry. Only fan-out children
            # (schemas with required parents) log it; every other schema stays quiet.
            if new_source.get_required_parent_schemas(schema.name):
                await logger.ainfo(
                    "data_imports.fanout_parent_source",
                    schema=schema.name,
                    parent_source="warehouse" if fanout_warehouse_reuse else "api",
                    source_type=source_type,
                )

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
                db_incremental_field_last_value_before_lookback=incremental_last_value_before_lookback,
                history_start=history_start,
                logger=logger,
                job_id=inputs.run_id,
                reset_pipeline=reset_pipeline,
                enabled_columns=schema.enabled_columns,
                row_filters=row_filters,
                schema_metadata=schema.schema_metadata,
                s3_folder_name=schema.resolved_s3_folder_name,
                # A schema-level override (user-managed) wins over the source pin.
                api_version=new_source.resolve_api_version(schema.api_version or model.pipeline.api_version),
                fanout_warehouse_reuse=fanout_warehouse_reuse,
            )

            try:
                config = new_source.parse_config(model.pipeline.job_inputs)
            except IntegrationSecretsFailure as e:
                # A source whose config carries a PostHog-owned credential resolves it here, so a
                # failure at this point is ours and not a corrupt `job_inputs`. Route it through the
                # shared policy: the branch below would read it as an unparseable config and disable
                # the customer's schema over a rotation they can't see and didn't cause.
                await _handle_import_error(job_inputs, logger, e)
            except Exception as e:
                # A stored config that can't be parsed (corrupt or double-encoded `job_inputs`)
                # fails identically on every attempt — there is nothing to retry. Treat it as
                # non-retryable so the job gives up cleanly instead of crash-looping and spamming
                # error tracking. Mirrors the skip in `sync_new_schemas_activity`.
                await handle_non_retryable_error(
                    job_inputs.team_id, str(job_inputs.source_id), job_inputs.run_id, str(e), logger, e
                )

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

                # This activity finalized the job itself just above, so the workflow must not
                # write a second terminal status — see PipelineResult for the ownership contract.
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


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class ImportJobModels:
    job: ExternalDataJob
    schema: ExternalDataSchema
    source: ExternalDataSource
    table: DataWarehouseTable | None


@database_sync_to_async_pool
def _get_models(
    job_id: str,
) -> ImportJobModels:
    # `schema__source` is prefetched so `job.folder_path()` (via `schema.source.source_type`, called
    # repeatedly through the run by `DeltaTableRef._get_delta_table_uri`) never triggers a lazy
    # relation load later on a pooled connection the transaction pooler may have dropped mid-sync,
    # which raises a transient `OperationalError`/DNS failure.
    job = ExternalDataJob.objects.select_related("schema", "schema__table", "schema__source").get(id=job_id)
    schema: ExternalDataSchema | None = job.schema
    source: ExternalDataSource | None = job.pipeline
    if schema is None:
        raise Exception("No schema attached to job")
    if source is None:
        raise Exception("No source attached to job")

    table: DataWarehouseTable | None = schema.table
    return ImportJobModels(job=job, schema=schema, source=source, table=table)


# What a customer reads when a PostHog-managed credential is unavailable. Deliberately says
# nothing about which credential: the name is ours (`HUBSPOT_APP_CLIENT_SECRET`), it means nothing
# to them, and naming it invites them to go looking for a setting they do not have. The full
# detail goes to the logs and, when a person needs to act, to error tracking.
INTEGRATION_CREDENTIAL_UNAVAILABLE_MESSAGE = (
    "A PostHog-managed credential for this source is temporarily unavailable. This sync will "
    "retry automatically — no action is needed on your side."
)


async def _handle_import_error(
    job_inputs: PipelineInputs,
    logger: FilteringBoundLogger,
    error: Exception,
) -> NoReturn:
    """Route an import error through the source's non-retryable error policy.

    Errors the source classifies as non-retryable (bad credentials, a deleted or
    misconfigured remote — e.g. a MongoDB ``mongodb+srv://`` hostname whose DNS record no
    longer resolves) are handed to ``handle_non_retryable_error``, which stops the job after
    a few attempts instead of retrying up to the activity's maximum.

    Errors the source classifies as retryable (rate limits, transient 5xx) reach us only after
    the source's own retries are exhausted. Temporal retries the whole activity and the error is
    transient and self-recovering, so we log at ``warning`` rather than ``exception`` and re-raise
    as ``NonReportableError`` — log level alone doesn't stop the activity interceptor
    (``posthog/temporal/common/posthog_client.py``) from reporting whatever exception type escapes
    the activity; only that marker type does. ``RESTClientRetryableError`` gets the same treatment
    by type, since it's already a ``NonReportableError`` subclass and every REST-based source hits
    that condition already. A transient object-store hiccup talking to our own data-warehouse
    bucket is re-raised as ``NonReportableError`` the same way, as is a Django
    ``OperationalError``/``InterfaceError`` (a connection-pool blip against our own app DB).

    Everything else is logged as an exception and re-raised so Temporal retries it as usual.
    """
    source_cls = SourceRegistry.get_source(job_inputs.job_type)
    error_msg = str(error)

    # The schema this activity is running for can be deleted (or soft-deleted) between the job
    # being created and this activity's mid-run re-fetch of it — every retry re-reads the same
    # gone row, so it never turns into data regardless of source. Classify it here by type rather
    # than depending on each source listing the message in get_non_retryable_errors.
    if isinstance(error, ExternalDataSchema.DoesNotExist):
        await handle_non_retryable_error(
            job_inputs.team_id, str(job_inputs.source_id), job_inputs.run_id, error_msg, logger, error
        )

    # The shared REST engine raises RESTClientNonRetryableError only for responses retrying can
    # never turn into data (a non-JSON body on an otherwise-successful response). Honor that
    # contract by type so every REST-based source stops immediately, rather than depending on each
    # source listing the message in get_non_retryable_errors.
    if isinstance(error, RESTClientNonRetryableError):
        await handle_non_retryable_error(
            job_inputs.team_id, str(job_inputs.source_id), job_inputs.run_id, error_msg, logger, error
        )

    # The shared REST engine compiles data_selector/cursor_path/next_url_path/resolve-param fields
    # as JSONPath at sync time (jsonpath_utils.compile_path), not at manifest-validation time. A
    # malformed path is a fixed string, so parsing it fails identically on every retry regardless
    # of source — classify it here by type (message text varies across jsonpath_ng's several parse-
    # and lex-error shapes, so it can't be matched via get_non_retryable_errors).
    if isinstance(error, JSONPathError):
        await handle_non_retryable_error(
            job_inputs.team_id, str(job_inputs.source_id), job_inputs.run_id, error_msg, logger, error
        )

    # Every credential the integration service holds is PostHog's own — the OAuth app secrets and
    # API keys we own, not anything the customer configured. So none of its failure states are
    # theirs to fix, and none are permanent: a key in recovery is re-provisioned, a missing key is
    # added, an unreachable service comes back. Retry, and if the budget runs out let the run fail
    # and the next scheduled sync pick it up.
    #
    # What must not happen is `handle_non_retryable_error`, which disables the schema and makes a
    # customer re-enable a sync they never broke. That is the whole reason this is classified here
    # by type rather than left to fall through: one credential going into recovery would otherwise
    # disable every sync of that source type, across every customer, until each was re-enabled by
    # hand — turning a reversible platform action into a wide manual recovery.
    #
    # Checked before the bare-404 rule below on purpose. That rule reads a 404 as "the customer's
    # endpoint is gone", and a misrouted INTEGRATION_SERVICE_URL answers 404 as well; the client
    # wraps its transport failures so the two can't be confused, and this ordering keeps that true
    # even if something later leaks a raw HTTPError.
    if isinstance(error, IntegrationSecretsFailure):
        if error.reportable:
            # A gap only PostHog can close (a key never added for this environment, a
            # half-configured deployment). Capture explicitly rather than letting it escape raw:
            # the message the customer ends up reading must not carry an internal credential name,
            # and error tracking still needs the real exception to group and route it.
            capture_exception(error)
            await logger.aexception(error_msg)
        else:
            await logger.awarning(error_msg)
        await logger.adebug("Integration service credential unavailable - re-raising for Temporal retry")
        raise NonReportableError(INTEGRATION_CREDENTIAL_UNAVAILABLE_MESSAGE) from error

    # A 404 from the shared REST engine's fallback `raise_for_status()` path means the configured
    # endpoint/resource doesn't exist — every retry replays the identical request against the same
    # dead URL. Unlike 401 (a token needing refresh, which the REST engine's own retry re-mints) or
    # 429/5xx (already RESTClientRetryableError), there's no self-recovering path for a 404, so
    # classify it here rather than depending on each REST-based source listing it.
    if isinstance(error, HTTPError) and error.response is not None and error.response.status_code == 404:
        await handle_non_retryable_error(
            job_inputs.team_id, str(job_inputs.source_id), job_inputs.run_id, error_msg, logger, error
        )

    # Raised in shared pipeline code when incoming data can't be cast into the stored (narrower)
    # Delta column type. delta-rs can't change a column's type in place, so this fails identically
    # on every retry regardless of source — classify it non-retryable by type here rather than
    # relying on each source listing the message in get_non_retryable_errors.
    if isinstance(error, SchemaColumnTypeChangedException):
        await handle_non_retryable_error(
            job_inputs.team_id, str(job_inputs.source_id), job_inputs.run_id, error_msg, logger, error
        )

    # An OAuth `Integration.access_token`/`refresh_token` that still looks like Fernet ciphertext
    # (a lost/rotated encryption key, a corrupted row) fails identically on every retry — the
    # third-party API sees the same garbage credential every time. Classify by type here, shared
    # across every OAuth-based source, rather than depending on each source's
    # get_non_retryable_errors to recognise this message.
    if isinstance(error, UndecryptedIntegrationSecretError):
        await handle_non_retryable_error(
            job_inputs.team_id, str(job_inputs.source_id), job_inputs.run_id, error_msg, logger, error
        )

    # RESTClientRetryableError only escapes the shared REST engine's own tenacity retry loop once
    # that budget (rate limits, transient 5xx, connection resets/timeouts) is exhausted — the same
    # "reaches us only after internal retries exhaust" contract as get_retryable_errors below.
    # Honor it by type so every REST-based source gets this benign, self-recovering failure logged
    # as a warning, rather than depending on each source separately listing "HTTP 429"/"HTTP 5xx"
    # in get_retryable_errors.
    if isinstance(error, RESTClientRetryableError):
        await logger.awarning(error_msg)
        await logger.adebug("REST client exhausted its retries - re-raising for Temporal retry")
        raise error

    # A transient S3/object-store hiccup talking to our own data-warehouse bucket (IMDS/STS
    # blip, SlowDown throttling) that surfaced during this run — e.g. resetting or opening the
    # Delta table. Not a PostHog defect and not a customer credential problem (see
    # TRANSIENT_OBJECT_STORE_ERRORS), and retrying resolves it, so it shouldn't page anyone.
    if is_transient_object_store_error(error):
        await logger.awarning(error_msg)
        await logger.adebug("Transient object-store error - re-raising for Temporal retry")
        raise NonReportableError(error_msg) from error

    # A Django OperationalError/InterfaceError here comes from a lookup against PostHog's own app
    # DB (e.g. resolving a team or CustomPropertySource for the person-property staging hook) —
    # every source that talks to a customer's own database (Postgres, MySQL, Redshift) does so over
    # a raw driver connection, never Django's ORM, so this exception type can only mean a transient
    # connection-pool blip on our side (e.g. a PgBouncer query_wait_timeout under load), not a
    # customer data or config problem. Same classification already used for app-DB blips in
    # delta_table_ref.is_transient_maintenance_error. PostHogInternalDatabaseError is the same
    # condition already reclassified by shared pipeline code (e.g. cdp_producer's should_run check)
    # specifically so it wouldn't be mistaken for a customer-side failure here — honor that by type.
    if isinstance(error, OperationalError | InterfaceError | PostHogInternalDatabaseError):
        await logger.awarning(error_msg)
        await logger.adebug("Transient app-DB error - re-raising for Temporal retry")
        raise NonReportableError(error_msg) from error

    # Cross-source non-retryable errors (missing primary key on an incremental table, bad SSH tunnel
    # auth, a widened column type) are raised from shared pipeline code, not any one source. The
    # finalization activity already consults this shared dict; this in-activity handler decides whether
    # to re-raise for a full retry, so without it a shared config error retries the activity's whole
    # budget and reports on every attempt. Merge it in — source-specific entries win on overlap.
    from products.warehouse_sources.backend.temporal.data_imports.external_data_job import (  # noqa: PLC0415 — deferred to break the external_data_job -> import_data_sync import cycle
        Any_Source_Errors,
    )

    non_retryable_errors = {**Any_Source_Errors, **source_cls.get_non_retryable_errors()}
    if error_message_matches(error_msg, non_retryable_errors):
        await handle_non_retryable_error(
            job_inputs.team_id, str(job_inputs.source_id), job_inputs.run_id, error_msg, logger, error
        )

    retryable_errors = source_cls.get_retryable_errors()
    if error_message_matches(error_msg, retryable_errors):
        await logger.awarning(error_msg)
        await logger.adebug("Source-classified retryable error - re-raising for Temporal retry")
        raise NonReportableError(error_msg) from error

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
        models = await _get_models(job_inputs.run_id)

        use_v3 = models.job.pipeline_version == ExternalDataJob.PipelineVersion.V3

        if use_v3:
            from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3 import PipelineV3

            logger.info("Running V3 pipeline (persisted job.pipeline_version is V3)")
            pipeline: PipelineV3 | PipelineNonDLT = PipelineV3(
                source_response,
                logger,
                job_inputs.run_id,
                reset_pipeline,
                shutdown_monitor,
                resumable_source_manager,
                models=models,
            )
        else:
            pipeline = PipelineNonDLT(
                source_response,
                logger,
                job_inputs.run_id,
                reset_pipeline,
                shutdown_monitor,
                resumable_source_manager,
                models=models,
            )

        result = await pipeline.run()
        del pipeline
        await logger.adebug("Finished running pipeline")
        return result
    except Exception as e:
        await _handle_import_error(job_inputs, logger, e)
