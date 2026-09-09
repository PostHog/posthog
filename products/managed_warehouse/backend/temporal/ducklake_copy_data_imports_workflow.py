from __future__ import annotations

import json
import time
import uuid
import typing
import datetime as dt
import dataclasses
from urllib.parse import urlparse

from django.conf import settings
from django.db import close_old_connections

import duckdb
import deltalake
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.metrics import Attributes, ExecutionTimeRecorder

from products.managed_warehouse.backend.common import (
    _get_org_id_for_team,
    attach_catalog,
    duckgres_data_imports_schema,
    duckgres_data_imports_table_name,
    get_config,
    get_duckgres_server_by_team_org,
    get_duckgres_server_for_organization,
    is_dev_mode,
)
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseSourceJobStatus,
    ManagedWarehouseSourceJobUpdate,
    ManagedWarehouseSourceJobWorkflow,
)
from products.managed_warehouse.backend.logic.verification import (
    DuckLakeCopyVerificationParameter,
    DuckLakeCopyVerificationQuery,
    get_data_imports_verification_queries,
)
from products.managed_warehouse.backend.storage import (
    DeltaTableSnapshotWorkload,
    cleanup_staged_files,
    compute_staging_uri,
    configure_connection,
    connect_to_duckgres,
    create_staging_read_secret,
    ensure_ducklake_bucket_exists,
    get_delta_table_snapshot_workload,
    get_deltalake_storage_options,
    setup_duckgres_session,
    stage_delta_table_with_workload,
)
from products.managed_warehouse.backend.temporal.metrics import (
    get_ducklake_copy_data_imports_bytes_metric,
    get_ducklake_copy_data_imports_duration_metric,
    get_ducklake_copy_data_imports_files_metric,
    get_ducklake_copy_data_imports_finished_metric,
    get_ducklake_copy_data_imports_last_success_metric,
    get_ducklake_copy_data_imports_rows_metric,
    get_ducklake_copy_data_imports_started_metric,
    get_ducklake_copy_data_imports_verification_metric,
    record_ducklake_copy_data_imports_stage_duration,
)
from products.managed_warehouse.backend.temporal.source_job_state import record_managed_warehouse_source_job_activity
from products.warehouse_sources.backend.facade.models import ExternalDataSchema

LOGGER = get_logger(__name__)
DATA_IMPORTS_DUCKLAKE_WORKFLOW_PREFIX = "data_imports"
DUCKLAKE_COPY_DATA_IMPORTS_STAGE_DURATION_METRIC = "ducklake_copy_data_imports_stage_duration"
_SOURCE_JOB_STATE_PATCH_ID = "ducklake-copy-source-job-state-2026-08"


def _copy_source_job_update(
    *,
    inputs: DataImportsDuckLakeCopyInputs,
    schema_ids: list[uuid.UUID],
    status: ManagedWarehouseSourceJobStatus,
    started_at: dt.datetime,
    finished_at: dt.datetime | None = None,
    latest_error: str | None = None,
) -> ManagedWarehouseSourceJobUpdate:
    workflow_id = None
    workflow_run_id = None
    if workflow.in_workflow():
        workflow_info = workflow.info()
        workflow_id = workflow_info.workflow_id
        workflow_run_id = workflow_info.run_id
    return ManagedWarehouseSourceJobUpdate(
        team_id=inputs.team_id,
        schema_ids=schema_ids,
        source_job_id=inputs.job_id,
        attempt_id=inputs.job_id,
        workflow_type=ManagedWarehouseSourceJobWorkflow.COPY,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        latest_error=latest_error,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
    )


async def _record_copy_source_job_state(
    *,
    inputs: DataImportsDuckLakeCopyInputs,
    schema_ids: list[uuid.UUID],
    status: ManagedWarehouseSourceJobStatus,
    started_at: dt.datetime,
    finished_at: dt.datetime | None = None,
    latest_error: str | None = None,
) -> None:
    if not schema_ids:
        return
    await workflow.execute_activity(
        record_managed_warehouse_source_job_activity,
        _copy_source_job_update(
            inputs=inputs,
            schema_ids=schema_ids,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            latest_error=latest_error,
        ),
        start_to_close_timeout=dt.timedelta(seconds=30),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )


async def _record_copy_terminal_source_job_state(
    *,
    inputs: DataImportsDuckLakeCopyInputs,
    schema_ids: list[uuid.UUID],
    status: ManagedWarehouseSourceJobStatus,
    started_at: dt.datetime,
    finished_at: dt.datetime,
) -> None:
    try:
        await _record_copy_source_job_state(
            inputs=inputs,
            schema_ids=schema_ids,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
        )
    except Exception:
        await _record_copy_source_job_state(
            inputs=inputs,
            schema_ids=schema_ids,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
        )


def _stage_timer(*, stage: str, team_id: int, schema_id: str | None = None) -> ExecutionTimeRecorder:
    attributes: Attributes = {"stage": stage, "team_id": str(team_id)}
    if schema_id is not None:
        attributes["schema_id"] = schema_id
    return ExecutionTimeRecorder(
        DUCKLAKE_COPY_DATA_IMPORTS_STAGE_DURATION_METRIC,
        "Execution duration of one post-gate DuckLake data import copy stage.",
        attributes,
        log=True,
        histogram_recorder=record_ducklake_copy_data_imports_stage_duration,
    )


def _bind_copy_activity_context(*, team_id: int, job_id: str, schema_id: str | None = None) -> None:
    identifiers: dict[str, str | int] = {"team_id": team_id, "job_id": job_id}
    if schema_id is not None:
        identifiers["schema_id"] = schema_id
    if activity.in_activity():
        workflow_id = activity.info().workflow_id
        if workflow_id is not None:
            identifiers["workflow_id"] = workflow_id
    bind_contextvars(**identifiers)


def _record_copy_workload(*, team_id: int, schema_id: str, workload: DeltaTableSnapshotWorkload) -> None:
    get_ducklake_copy_data_imports_files_metric(team_id=team_id, schema_id=schema_id).record(float(workload.file_count))
    if workload.row_count is not None:
        get_ducklake_copy_data_imports_rows_metric(team_id=team_id, schema_id=schema_id).record(
            float(workload.row_count)
        )
    if workload.byte_count is not None:
        get_ducklake_copy_data_imports_bytes_metric(team_id=team_id, schema_id=schema_id).record(
            float(workload.byte_count)
        )


class _VerificationCursor(typing.Protocol):
    @property
    def description(self) -> typing.Sequence[object] | None: ...

    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class _VerificationConnection(typing.Protocol):
    def execute(self, query: str, params: typing.Sequence[object] | None = None) -> _VerificationCursor: ...


@dataclasses.dataclass
class DuckLakeCopyWorkflowGateInputs:
    """Inputs for the DuckLake copy workflow gate activity."""

    team_id: int


@dataclasses.dataclass
class DataImportsDuckLakeCopyInputs:
    """Workflow inputs passed to DuckLakeCopyDataImportsWorkflow."""

    team_id: int
    job_id: str
    schema_ids: list[uuid.UUID]

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "job_id": self.job_id,
            "schema_ids": [str(sid) for sid in self.schema_ids],
        }


@dataclasses.dataclass
class DuckLakeCopyDataImportsMetadata:
    """Metadata for a data imports schema to copy into DuckLake."""

    # General
    model_label: str

    # Source (Delta table)
    source_schema_id: str
    source_schema_name: str
    source_normalized_name: str
    source_table_uri: str

    # Destination (DuckLake)
    ducklake_schema_name: str
    ducklake_table_name: str

    # Source metadata (optional, with defaults)
    source_partition_column: str | None = None

    # Staging (duckgres path)
    staging_uri: str | None = None

    # Verification
    verification_queries: list[DuckLakeCopyVerificationQuery] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class DuckLakeCopyDataImportsActivityInputs:
    """Inputs for a single model copy activity."""

    team_id: int
    job_id: str
    model: DuckLakeCopyDataImportsMetadata


@dataclasses.dataclass
class DuckLakeCopyDataImportsVerificationResult:
    """Result of a single verification check for data imports DuckLake copy."""

    name: str
    passed: bool
    observed_value: float | None = None
    expected_value: float | None = None
    tolerance: float | None = None
    description: str | None = None
    sql: str | None = None
    error: str | None = None


@activity.defn
async def ducklake_copy_data_imports_gate_activity(inputs: DuckLakeCopyWorkflowGateInputs) -> bool:
    """Evaluate whether the DuckLake data imports copy workflow should run for a team."""
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    try:
        team = await database_sync_to_async(Team.objects.only("uuid", "organization_id").get)(id=inputs.team_id)
    except Team.DoesNotExist:
        await logger.aerror("Team does not exist when evaluating DuckLake data imports gate")
        return False

    try:
        return feature_enabled_or_false(
            "ducklake-data-imports-copy-workflow",
            str(team.uuid),
            groups={
                "organization": str(team.organization_id),
                "project": str(team.id),
            },
            group_properties={
                "organization": {
                    "id": str(team.organization_id),
                },
                "project": {
                    "id": str(team.id),
                },
            },
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception as error:
        await logger.awarning(
            "Failed to evaluate DuckLake data imports feature flag",
            error=str(error),
        )
        capture_exception(error)
        return False


@activity.defn
async def prepare_data_imports_ducklake_metadata_activity(
    inputs: DataImportsDuckLakeCopyInputs,
) -> list[DuckLakeCopyDataImportsMetadata]:
    """Resolve data imports schemas referenced in the workflow inputs into copy-ready metadata."""
    _bind_copy_activity_context(team_id=inputs.team_id, job_id=inputs.job_id)
    logger = LOGGER.bind()

    with _stage_timer(stage="prepare", team_id=inputs.team_id):
        return await _prepare_data_imports_ducklake_metadata(inputs, logger)


async def _prepare_data_imports_ducklake_metadata(
    inputs: DataImportsDuckLakeCopyInputs, logger: typing.Any
) -> list[DuckLakeCopyDataImportsMetadata]:
    if not inputs.schema_ids:
        await logger.ainfo("DuckLake copy requested but no schema_ids were provided - skipping")
        return []

    # All schemas in the batch belong to one team, so resolve the destination once.
    ducklake_schema_name = await database_sync_to_async(duckgres_data_imports_schema)(inputs.team_id)

    model_list: list[DuckLakeCopyDataImportsMetadata] = []

    for schema_id in inputs.schema_ids:
        schema = await database_sync_to_async(ExternalDataSchema.objects.select_related("team", "table", "source").get)(
            id=schema_id, team_id=inputs.team_id
        )

        normalized_name = schema.normalized_name
        source_type = schema.source.source_type

        source_table_uri = _data_imports_source_table_uri(schema)
        staging_uri = await database_sync_to_async(_resolve_data_imports_staging_uri)(
            source_table_uri, team_id=inputs.team_id
        )

        # Get partition column from Delta metadata (source of truth)
        partition_column = await database_sync_to_async(_detect_data_imports_partition_column)(
            source_table_uri, team_id=inputs.team_id
        )

        model_list.append(
            DuckLakeCopyDataImportsMetadata(
                model_label=f"{source_type}_{normalized_name}",
                source_schema_id=str(schema.id),
                source_schema_name=schema.name,
                source_normalized_name=normalized_name,
                source_table_uri=source_table_uri,
                ducklake_schema_name=ducklake_schema_name,
                ducklake_table_name=await database_sync_to_async(duckgres_data_imports_table_name)(schema),
                verification_queries=list(get_data_imports_verification_queries(normalized_name)),
                source_partition_column=partition_column,
                staging_uri=staging_uri,
            )
        )

    return model_list


@activity.defn
def copy_data_imports_to_ducklake_activity(
    inputs: DuckLakeCopyDataImportsActivityInputs,
) -> DeltaTableSnapshotWorkload:
    """Copy a single data imports schema's Delta snapshot into DuckLake."""
    schema_id = inputs.model.source_schema_id
    _bind_copy_activity_context(team_id=inputs.team_id, schema_id=schema_id, job_id=inputs.job_id)
    logger = LOGGER.bind(model_label=inputs.model.model_label, job_id=inputs.job_id)
    # This activity runs in a long-lived worker thread that never goes through Django's
    # request/response cycle, so a connection killed by the DB/proxy (e.g. after
    # CONN_MAX_AGE) is never detected and closed before reuse.
    if not settings.TEST:
        close_old_connections()

    heartbeater = HeartbeaterSync(details=("ducklake_copy", inputs.model.model_label), logger=logger)
    with heartbeater, _stage_timer(stage="copy", team_id=inputs.team_id, schema_id=schema_id):
        if is_dev_mode():
            return _copy_data_imports_via_duckdb(inputs, logger)
        return _copy_data_imports_via_duckgres(inputs, logger)


def _copy_data_imports_via_duckdb(
    inputs: DuckLakeCopyDataImportsActivityInputs, logger: typing.Any
) -> DeltaTableSnapshotWorkload:
    """Create the DuckLake table directly from Delta using the local DuckDB client."""
    workload = get_delta_table_snapshot_workload(inputs.model.source_table_uri, team_id=inputs.team_id)
    alias = "ducklake"
    with duckdb.connect() as conn:
        config = get_config()
        configure_connection(conn)
        ensure_ducklake_bucket_exists(config=config, team_id=inputs.team_id)
        _attach_ducklake_catalog(conn, config, alias=alias)

        qualified_schema = f"{alias}.{inputs.model.ducklake_schema_name}"
        qualified_table = f"{qualified_schema}.{inputs.model.ducklake_table_name}"

        logger.info(
            "Creating DuckLake table from Delta snapshot",
            ducklake_table=qualified_table,
            source_table=inputs.model.source_table_uri,
        )
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {qualified_schema}")
        conn.execute(
            f"CREATE OR REPLACE TABLE {qualified_table} AS SELECT * FROM delta_scan(?)",
            [inputs.model.source_table_uri],
        )
        logger.info("Successfully materialized DuckLake table", ducklake_table=qualified_table)

    return workload


# A v3 full-refresh sync purges the source Delta table during extract and the
# delta-load consumer rebuilds it asynchronously after the import job (and therefore
# this copy, fired at job end) has already started. Reads that land in that window see
# an empty _delta_log. The wait budget covers the p99.9 of observed rebuild latency;
# a consumer outage beyond it fails the copy, and the next sync retries.
DELTA_REBUILD_WAIT_SECONDS = 600
DELTA_REBUILD_POLL_SECONDS = 20


def _is_delta_table_absent_error(error: Exception) -> bool:
    """Whether an error means the source Delta table does not currently exist."""
    if isinstance(error, deltalake.exceptions.TableNotFoundError):
        return True
    return isinstance(error, deltalake.exceptions.DeltaError) and "No files in log segment" in str(error)


def _stage_delta_table_waiting_for_rebuild(
    *, source_uri: str, catalog_bucket: str, organization_id: str, logger: typing.Any
) -> DeltaTableSnapshotWorkload:
    """Stage the source Delta table, waiting out the v3 full-refresh rebuild window.

    Only the two "table momentarily absent" signals are absorbed; every other error
    propagates immediately. Runs inside the activity's HeartbeaterSync, so the sleeps
    keep heartbeating and a dead worker is still detected via heartbeat timeout.
    """
    deadline = time.monotonic() + DELTA_REBUILD_WAIT_SECONDS
    while True:
        try:
            staged_table = stage_delta_table_with_workload(
                source_uri=source_uri,
                catalog_bucket=catalog_bucket,
                organization_id=organization_id,
            )
            return staged_table.workload
        except Exception as error:
            if not _is_delta_table_absent_error(error) or time.monotonic() >= deadline:
                raise
            logger.info(
                "Source Delta table not readable yet, waiting for the loader to rebuild it",
                source_uri=source_uri,
                error=str(error),
                poll_seconds=DELTA_REBUILD_POLL_SECONDS,
            )
            time.sleep(DELTA_REBUILD_POLL_SECONDS)


def _copy_data_imports_via_duckgres(
    inputs: DuckLakeCopyDataImportsActivityInputs, logger: typing.Any
) -> DeltaTableSnapshotWorkload:
    """Stage Delta files and create the DuckLake table via duckgres."""
    org_id = _get_org_id_for_team(inputs.team_id)
    server = get_duckgres_server_for_organization(org_id)
    if server is None:
        raise ApplicationError(f"No DuckgresServer configured for team {inputs.team_id}", non_retryable=True)
    bucket = server.bucket
    if not bucket:
        raise ApplicationError(f"No S3 bucket configured for team {inputs.team_id}", non_retryable=True)
    if not inputs.model.staging_uri:
        raise ApplicationError(f"No staging_uri for model {inputs.model.model_label}", non_retryable=True)

    logger.info(
        "Staging Delta files for duckgres",
        source_uri=inputs.model.source_table_uri,
        staging_uri=inputs.model.staging_uri,
    )
    workload = _stage_delta_table_waiting_for_rebuild(
        source_uri=inputs.model.source_table_uri,
        catalog_bucket=bucket,
        organization_id=org_id,
        logger=logger,
    )

    schema = inputs.model.ducklake_schema_name
    table = f"{schema}.{inputs.model.ducklake_table_name}"

    with connect_to_duckgres(server, application_name="ducklake-copy") as conn:
        setup_duckgres_session(conn)
        create_staging_read_secret(conn, bucket)
        logger.info(
            "Creating DuckLake table from staged Delta snapshot via duckgres",
            ducklake_table=table,
            staging_uri=inputs.model.staging_uri,
        )
        conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        conn.execute(
            f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM delta_scan(%s)",
            [inputs.model.staging_uri],
        )
        logger.info("Successfully materialized DuckLake table via duckgres", ducklake_table=table)

    return workload


@dataclasses.dataclass
class DuckLakeDataImportsStagingCleanupInputs:
    team_id: int
    staging_uri: str
    schema_id: str | None = None
    job_id: str = ""


@activity.defn
def cleanup_data_imports_staging_activity(inputs: DuckLakeDataImportsStagingCleanupInputs) -> None:
    """Clean up staged Delta files after successful verification."""
    _bind_copy_activity_context(team_id=inputs.team_id, schema_id=inputs.schema_id, job_id=inputs.job_id)
    # Same long-lived worker thread caveat as copy_data_imports_to_ducklake_activity.
    if not settings.TEST:
        close_old_connections()
    with _stage_timer(stage="cleanup", team_id=inputs.team_id, schema_id=inputs.schema_id):
        server = get_duckgres_server_by_team_org(inputs.team_id)
        if server is None:
            return
        cleanup_staged_files(
            staging_uri=inputs.staging_uri,
        )


def _data_imports_source_table_uri(schema: ExternalDataSchema) -> str:
    """S3 URI of the schema's Delta table, matching the folder the loader actually wrote.

    Uses ``normalized_s3_folder_name`` (the resolved folder leaf), which diverges from
    ``normalized_name`` for folder-pinned sources (e.g. Postgres ``public.users`` → folder
    ``users``). Reading ``normalized_name`` here points at a prefix with no ``_delta_log``
    and surfaces as "No files in log segment".
    """
    return f"{settings.BUCKET_URL}/{schema.folder_path()}/{schema.normalized_s3_folder_name}"


def _resolve_data_imports_staging_uri(source_uri: str, *, team_id: int) -> str | None:
    """Return the staged Delta URI required by prod duckgres, or None for local dev."""
    if is_dev_mode():
        return None

    server = get_duckgres_server_by_team_org(team_id)
    if server is None:
        raise ApplicationError(f"No DuckgresServer configured for team {team_id}", non_retryable=True)
    if not server.bucket:
        raise ApplicationError(f"No S3 bucket configured for team {team_id}", non_retryable=True)

    return compute_staging_uri(source_uri, server.bucket)


def _detect_data_imports_partition_column(table_uri: str, *, team_id: int) -> str | None:
    """Detect partition column from Delta metadata (source of truth)."""
    if not table_uri:
        return None
    partition_columns = _fetch_delta_partition_columns(table_uri, team_id=team_id)
    return partition_columns[0] if partition_columns else None


def _fetch_delta_partition_columns(table_uri: str, *, team_id: int) -> list[str]:
    """Fetch partition columns from Delta table metadata."""
    options = get_deltalake_storage_options(team_id=team_id)
    try:
        delta_table = deltalake.DeltaTable(table_uri=table_uri, storage_options=options)
    except Exception as exc:
        LOGGER.bind(table_uri=table_uri).debug("Delta partition detection failed to open table", error=str(exc))
        return []

    try:
        metadata = delta_table.metadata()
    except Exception as exc:
        LOGGER.bind(table_uri=table_uri).debug("Delta partition detection failed to read metadata", error=str(exc))
        return []

    partition_columns = getattr(metadata, "partition_columns", None) or []
    return [column for column in partition_columns if column]


def _attach_ducklake_catalog(conn: duckdb.DuckDBPyConnection, config: dict[str, str], alias: str) -> None:
    """Attach the DuckLake catalog, swallowing the error if already attached."""
    try:
        attach_catalog(conn, config, alias=alias)
    except duckdb.CatalogException as exc:
        if alias not in str(exc):
            raise


@activity.defn
def verify_data_imports_ducklake_copy_activity(
    inputs: DuckLakeCopyDataImportsActivityInputs,
) -> list[DuckLakeCopyDataImportsVerificationResult]:
    """Run configured verification queries to ensure the copy matches the source."""
    schema_id = inputs.model.source_schema_id
    _bind_copy_activity_context(team_id=inputs.team_id, schema_id=schema_id, job_id=inputs.job_id)
    logger = LOGGER.bind(model_label=inputs.model.model_label, job_id=inputs.job_id)
    # Same long-lived worker thread caveat as copy_data_imports_to_ducklake_activity.
    if not settings.TEST:
        close_old_connections()

    with _stage_timer(stage="verify", team_id=inputs.team_id, schema_id=schema_id):
        return _verify_data_imports_ducklake_copy(inputs, logger)


def _verify_data_imports_ducklake_copy(
    inputs: DuckLakeCopyDataImportsActivityInputs, logger: typing.Any
) -> list[DuckLakeCopyDataImportsVerificationResult]:
    if not inputs.model.verification_queries:
        logger.info("No DuckLake verification queries configured - skipping")
        return []

    heartbeater = HeartbeaterSync(details=("ducklake_verify", inputs.model.model_label), logger=logger)
    with heartbeater:
        if is_dev_mode():
            results = _verify_data_imports_ducklake_copy_via_duckdb(inputs, logger)
        else:
            results = _verify_data_imports_ducklake_copy_via_duckgres(inputs, logger)

    failed = [result for result in results if not result.passed]
    if failed:
        logger.warning(
            "DuckLake verification checks failed",
            model_label=inputs.model.model_label,
            failures=[dataclasses.asdict(result) for result in failed],
        )

    return results


def _verify_data_imports_ducklake_copy_via_duckdb(
    inputs: DuckLakeCopyDataImportsActivityInputs, logger: typing.Any
) -> list[DuckLakeCopyDataImportsVerificationResult]:
    alias = "ducklake"
    config = get_config()

    with duckdb.connect() as conn:
        configure_connection(conn)
        _attach_ducklake_catalog(conn, config, alias=alias)

        ducklake_table = f"{alias}.{inputs.model.ducklake_schema_name}.{inputs.model.ducklake_table_name}"
        format_values = _get_data_imports_verification_format_values(
            ducklake_table=ducklake_table,
            ducklake_schema=f"{alias}.{inputs.model.ducklake_schema_name}",
            ducklake_alias=alias,
            inputs=inputs,
        )
        return _run_data_imports_verification_checks(
            conn,
            inputs,
            ducklake_table,
            format_values,
            source_uri=inputs.model.source_table_uri,
            parameter_placeholder="?",
            logger=logger,
        )


def _verify_data_imports_ducklake_copy_via_duckgres(
    inputs: DuckLakeCopyDataImportsActivityInputs, logger: typing.Any
) -> list[DuckLakeCopyDataImportsVerificationResult]:
    org_id = _get_org_id_for_team(inputs.team_id)
    server = get_duckgres_server_for_organization(org_id)
    if server is None:
        raise ApplicationError(f"No DuckgresServer configured for team {inputs.team_id}", non_retryable=True)
    if not inputs.model.staging_uri:
        raise ApplicationError(f"No staging_uri for model {inputs.model.model_label}", non_retryable=True)

    ducklake_table = f"{inputs.model.ducklake_schema_name}.{inputs.model.ducklake_table_name}"
    format_values = _get_data_imports_verification_format_values(
        ducklake_table=ducklake_table,
        ducklake_schema=inputs.model.ducklake_schema_name,
        ducklake_alias="",
        inputs=inputs,
    )

    with connect_to_duckgres(server, application_name="ducklake-copy") as conn:
        setup_duckgres_session(conn)
        create_staging_read_secret(conn, urlparse(inputs.model.staging_uri).netloc)
        return _run_data_imports_verification_checks(
            conn,
            inputs,
            ducklake_table,
            format_values,
            source_uri=inputs.model.staging_uri,
            parameter_placeholder="%s",
            logger=logger,
        )


def _get_data_imports_verification_format_values(
    *,
    ducklake_table: str,
    ducklake_schema: str,
    ducklake_alias: str,
    inputs: DuckLakeCopyDataImportsActivityInputs,
) -> dict[str, str]:
    return {
        "ducklake_table": ducklake_table,
        "ducklake_schema": ducklake_schema,
        "ducklake_alias": ducklake_alias,
        "schema_name": inputs.model.ducklake_schema_name,
        "table_name": inputs.model.ducklake_table_name,
    }


def _run_data_imports_verification_checks(
    conn: _VerificationConnection,
    inputs: DuckLakeCopyDataImportsActivityInputs,
    ducklake_table: str,
    format_values: dict[str, str],
    *,
    source_uri: str,
    parameter_placeholder: str,
    logger: typing.Any,
) -> list[DuckLakeCopyDataImportsVerificationResult]:
    results: list[DuckLakeCopyDataImportsVerificationResult] = []

    for query in inputs.model.verification_queries:
        rendered_sql = query.sql.format(**format_values)
        if parameter_placeholder != "?":
            rendered_sql = _replace_duckdb_parameter_placeholders(rendered_sql, parameter_placeholder)
        params = [
            _resolve_data_imports_verification_parameter(param, inputs, source_uri_override=source_uri)
            for param in query.parameters
        ]

        try:
            row = conn.execute(rendered_sql, params).fetchone()
        except Exception as exc:
            logger.warning(
                "DuckLake verification query failed",
                check=query.name,
                error=str(exc),
            )
            results.append(
                DuckLakeCopyDataImportsVerificationResult(
                    name=query.name,
                    passed=False,
                    expected_value=query.expected_value,
                    tolerance=query.tolerance,
                    description=query.description,
                    sql=rendered_sql,
                    error=str(exc),
                )
            )
            continue

        if not row:
            logger.warning("DuckLake verification query returned no rows", check=query.name)
            results.append(
                DuckLakeCopyDataImportsVerificationResult(
                    name=query.name,
                    passed=False,
                    expected_value=query.expected_value,
                    tolerance=query.tolerance,
                    description=query.description,
                    sql=rendered_sql,
                    error="Query returned no rows",
                )
            )
            continue

        raw_value = typing.cast(str | bytes | int | float, row[0])
        try:
            observed = float(raw_value)
        except (TypeError, ValueError):
            logger.warning(
                "DuckLake verification query returned a non-numeric value",
                check=query.name,
                value=raw_value,
            )
            results.append(
                DuckLakeCopyDataImportsVerificationResult(
                    name=query.name,
                    passed=False,
                    expected_value=query.expected_value,
                    tolerance=query.tolerance,
                    description=query.description,
                    sql=rendered_sql,
                    error="Query did not return a numeric value",
                )
            )
            continue

        diff = abs(observed - (query.expected_value or 0.0))
        tolerance = query.tolerance or 0.0
        passed = diff <= tolerance
        log_method = logger.info if passed else logger.warning
        log_method(
            "DuckLake verification result",
            check=query.name,
            observed_value=observed,
            expected_value=query.expected_value,
            tolerance=tolerance,
        )

        results.append(
            DuckLakeCopyDataImportsVerificationResult(
                name=query.name,
                passed=passed,
                observed_value=observed,
                expected_value=query.expected_value,
                tolerance=tolerance,
                description=query.description,
                sql=rendered_sql,
            )
        )

    schema_result = _run_data_imports_schema_verification(
        conn,
        ducklake_table,
        inputs,
        source_uri_override=source_uri,
        parameter_placeholder=parameter_placeholder,
    )
    if schema_result:
        results.append(schema_result)

    partition_result = _run_data_imports_partition_verification(
        conn,
        ducklake_table,
        inputs,
        source_uri_override=source_uri,
        parameter_placeholder=parameter_placeholder,
    )
    if partition_result:
        results.append(partition_result)

    return results


def _replace_duckdb_parameter_placeholders(sql: str, placeholder: str) -> str:
    return sql.replace("?", placeholder)


def _resolve_data_imports_verification_parameter(
    parameter: DuckLakeCopyVerificationParameter,
    inputs: DuckLakeCopyDataImportsActivityInputs,
    *,
    source_uri_override: str | None = None,
) -> str | int:
    """Resolve a verification parameter to its runtime value."""
    model = inputs.model
    mapping: dict[DuckLakeCopyVerificationParameter, str | int] = {
        DuckLakeCopyVerificationParameter.TEAM_ID: inputs.team_id,
        DuckLakeCopyVerificationParameter.JOB_ID: inputs.job_id,
        DuckLakeCopyVerificationParameter.MODEL_LABEL: model.model_label,
        DuckLakeCopyVerificationParameter.NORMALIZED_NAME: model.source_normalized_name,
        DuckLakeCopyVerificationParameter.SOURCE_TABLE_URI: source_uri_override or model.source_table_uri,
        DuckLakeCopyVerificationParameter.SCHEMA_NAME: model.ducklake_schema_name,
        DuckLakeCopyVerificationParameter.TABLE_NAME: model.ducklake_table_name,
    }

    if parameter not in mapping:
        raise ValueError(f"Unsupported DuckLake verification parameter '{parameter}'")

    return mapping[parameter]


def _run_data_imports_schema_verification(
    conn: _VerificationConnection,
    ducklake_table: str,
    inputs: DuckLakeCopyDataImportsActivityInputs,
    *,
    source_uri_override: str | None = None,
    parameter_placeholder: str = "?",
) -> DuckLakeCopyDataImportsVerificationResult | None:
    """Compare schema between Delta source and DuckLake table."""
    effective_source_uri = source_uri_override or inputs.model.source_table_uri
    try:
        source_schema = _fetch_delta_schema(conn, effective_source_uri, parameter_placeholder=parameter_placeholder)
        ducklake_schema = _fetch_schema(conn, ducklake_table)
    except Exception as exc:
        return DuckLakeCopyDataImportsVerificationResult(
            name="data_imports.schema_hash",
            passed=False,
            description="Compare schema hash between Delta source and DuckLake table.",
            error=str(exc),
        )

    mismatches = _diff_schema(source_schema, ducklake_schema)
    passed = not mismatches
    error = None
    if not passed:
        preview = "; ".join(mismatches[:5])
        if len(mismatches) > 5:
            preview = f"{preview}; +{len(mismatches) - 5} more differences"
        error = f"Schema mismatch: {preview}"

    return DuckLakeCopyDataImportsVerificationResult(
        name="data_imports.schema_hash",
        passed=passed,
        description="Compare schema hash between Delta source and DuckLake table.",
        expected_value=0.0,
        observed_value=0.0 if passed else 1.0,
        tolerance=0.0,
        error=error,
    )


def _run_data_imports_partition_verification(
    conn: _VerificationConnection,
    ducklake_table: str,
    inputs: DuckLakeCopyDataImportsActivityInputs,
    *,
    source_uri_override: str | None = None,
    parameter_placeholder: str = "?",
) -> DuckLakeCopyDataImportsVerificationResult | None:
    """Verify partition counts match between source and DuckLake."""
    effective_source_uri = source_uri_override or inputs.model.source_table_uri
    partition_column = inputs.model.source_partition_column
    if not partition_column:
        return None

    # Get partition column type from Delta schema directly
    source_schema = _fetch_delta_schema(conn, effective_source_uri, parameter_placeholder=parameter_placeholder)
    partition_column_type = _get_column_type_from_schema(source_schema, partition_column)
    if partition_column_type is None:
        # Partition column doesn't exist in Delta schema - skip verification
        return DuckLakeCopyDataImportsVerificationResult(
            name="data_imports.partition_counts",
            passed=False,
            description="Ensure partition counts match between source and DuckLake.",
            error=f"Partition column '{partition_column}' not found in Delta schema",
        )

    bucket_expr = _build_partition_bucket_expression(partition_column, partition_column_type)
    sql = f"""
        WITH source AS (
            SELECT {bucket_expr} AS bucket, count(*) AS cnt
            FROM delta_scan({parameter_placeholder})
            GROUP BY 1
        ),
        ducklake AS (
            SELECT {bucket_expr} AS bucket, count(*) AS cnt
            FROM {ducklake_table}
            GROUP BY 1
        )
        SELECT COALESCE(source.bucket, ducklake.bucket) AS bucket,
               COALESCE(source.cnt, 0) AS source_count,
               COALESCE(ducklake.cnt, 0) AS ducklake_count
        FROM source
        FULL OUTER JOIN ducklake USING (bucket)
        WHERE COALESCE(source.cnt, 0) != COALESCE(ducklake.cnt, 0)
        ORDER BY bucket
    """

    try:
        mismatches = conn.execute(sql, [effective_source_uri]).fetchall()
    except Exception as exc:
        return DuckLakeCopyDataImportsVerificationResult(
            name="data_imports.partition_counts",
            passed=False,
            description="Ensure partition counts match between source and DuckLake.",
            error=str(exc),
        )

    if mismatches:
        return DuckLakeCopyDataImportsVerificationResult(
            name="data_imports.partition_counts",
            passed=False,
            description="Ensure partition counts match between source and DuckLake.",
            expected_value=0.0,
            observed_value=float(len(mismatches)),
            tolerance=0.0,
            error=f"Partition mismatches detected: {mismatches[:5]}",
        )

    return DuckLakeCopyDataImportsVerificationResult(
        name="data_imports.partition_counts",
        passed=True,
        description="Ensure partition counts match between source and DuckLake.",
        expected_value=0.0,
        observed_value=0.0,
        tolerance=0.0,
    )


def _fetch_delta_schema(
    conn: _VerificationConnection, source_uri: str, *, parameter_placeholder: str = "?"
) -> list[tuple[str, str]]:
    """Fetch schema from a Delta table."""
    cursor = conn.execute(
        f"SELECT * FROM delta_scan({parameter_placeholder}) LIMIT 0",
        [source_uri],
    )
    return _schema_from_cursor_description(cursor)


def _get_column_type_from_schema(schema: list[tuple[str, str]], column_name: str) -> str | None:
    """Get a column's type from a schema list, case-insensitive."""
    normalized_name = column_name.lower()
    for name, col_type in schema:
        if name.lower() == normalized_name:
            return col_type
    return None


def _fetch_schema(conn: _VerificationConnection, table_name: str) -> list[tuple[str, str]]:
    """Fetch schema from a DuckLake table."""
    cursor = conn.execute(f"SELECT * FROM {table_name} LIMIT 0")
    return _schema_from_cursor_description(cursor)


def _schema_from_cursor_description(cursor: _VerificationCursor) -> list[tuple[str, str]]:
    description = cursor.description
    if not description:
        raise ValueError("Schema query did not return column metadata")

    schema: list[tuple[str, str]] = []
    for column in description:
        name = getattr(column, "name", None)
        type_code = getattr(column, "type_code", None)
        if name is None and isinstance(column, tuple):
            name = column[0] if len(column) > 0 else None
            type_code = column[1] if len(column) > 1 else None
        schema.append((str(name or ""), str(type_code or "")))
    return schema


def _diff_schema(source_schema: list[tuple[str, str]], ducklake_schema: list[tuple[str, str]]) -> list[str]:
    """Compare schemas and return list of mismatches."""
    mismatches: list[str] = []
    source_map = _schema_map(source_schema)
    ducklake_map = _schema_map(ducklake_schema)

    source_keys = set(source_map.keys())
    ducklake_keys = set(ducklake_map.keys())

    for key in sorted(source_keys - ducklake_keys):
        column_name, _ = source_map[key]
        mismatches.append(f"{column_name} missing from DuckLake")

    for key in sorted(ducklake_keys - source_keys):
        column_name, _ = ducklake_map[key]
        mismatches.append(f"{column_name} missing from Delta source")

    for key in sorted(source_keys & ducklake_keys):
        source_name, source_type = source_map[key]
        _, ducklake_type = ducklake_map[key]
        if source_type != ducklake_type:
            mismatches.append(f"{source_name} type mismatch (delta={source_type}, ducklake={ducklake_type})")

    return mismatches


def _schema_map(schema: list[tuple[str, str]]) -> dict[str, tuple[str, str]]:
    """Create a normalized map of column names to (original_name, type)."""
    mapping: dict[str, tuple[str, str]] = {}
    for name, column_type in schema:
        normalized_name = (name or "").strip().lower()
        mapping[normalized_name] = (name, (column_type or "").strip())
    return mapping


def _build_partition_bucket_expression(column_name: str, column_type: str | None) -> str:
    """Build a SQL expression for partition bucketing."""
    column_expr = _quote_identifier(column_name)
    if _is_datetime_column_type(column_type):
        return f"date_trunc('day', {column_expr})"
    return column_expr


def _is_datetime_column_type(column_type: str | None) -> bool:
    """Check if a DuckDB column type is a datetime type."""
    if not column_type:
        return False
    normalized = column_type.strip().lower()
    return "date" in normalized or "time" in normalized


def _quote_identifier(identifier: str) -> str:
    """Quote a SQL identifier."""
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


@workflow.defn(name="ducklake-copy.data-imports")
class DuckLakeCopyDataImportsWorkflow(PostHogWorkflow):
    """Temporal workflow that copies data imports into the DuckLake bucket."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> DataImportsDuckLakeCopyInputs:
        loaded = json.loads(inputs[0])
        schema_ids = [uuid.UUID(sid) if isinstance(sid, str) else sid for sid in loaded.get("schema_ids", [])]
        return DataImportsDuckLakeCopyInputs(
            team_id=loaded["team_id"],
            job_id=loaded["job_id"],
            schema_ids=schema_ids,
        )

    @workflow.run
    async def run(self, inputs: DataImportsDuckLakeCopyInputs) -> None:
        logger = LOGGER.bind(**inputs.properties_to_log)
        if workflow.in_workflow():
            logger = logger.bind(workflow_id=workflow.info().workflow_id)
        logger.info("Starting DuckLakeCopyDataImportsWorkflow")

        if not inputs.schema_ids:
            logger.info("No schema_ids to copy - exiting early")
            return

        should_copy = await workflow.execute_activity(
            ducklake_copy_data_imports_gate_activity,
            DuckLakeCopyWorkflowGateInputs(team_id=inputs.team_id),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        if not should_copy:
            logger.info("DuckLake copy workflow disabled by feature flag")
            return

        track_source_job_state = workflow.patched(_SOURCE_JOB_STATE_PATCH_ID)
        workflow_started_at = workflow.now()
        get_ducklake_copy_data_imports_started_metric(team_id=inputs.team_id).add(1)
        pending_staging_cleanup: list[DuckLakeDataImportsStagingCleanupInputs] = []
        pending_schema_ids = set(inputs.schema_ids)
        status = "failed"
        try:
            if track_source_job_state:
                await _record_copy_source_job_state(
                    inputs=inputs,
                    schema_ids=inputs.schema_ids,
                    status=ManagedWarehouseSourceJobStatus.RUNNING,
                    started_at=workflow_started_at,
                )
            model_list: list[DuckLakeCopyDataImportsMetadata] = await workflow.execute_activity(
                prepare_data_imports_ducklake_metadata_activity,
                inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            schema_ids_by_value = {str(schema_id): schema_id for schema_id in inputs.schema_ids}
            active_schema_ids = {schema_ids_by_value[model.source_schema_id] for model in model_list}
            skipped_schema_ids = pending_schema_ids - active_schema_ids
            if skipped_schema_ids:
                pending_schema_ids.difference_update(skipped_schema_ids)
                if track_source_job_state:
                    await _record_copy_terminal_source_job_state(
                        inputs=inputs,
                        schema_ids=list(skipped_schema_ids),
                        status=ManagedWarehouseSourceJobStatus.SKIPPED,
                        started_at=workflow_started_at,
                        finished_at=workflow.now(),
                    )

            if not model_list:
                status = "skipped"
                logger.info("No DuckLake copy metadata resolved - nothing to do")
                return

            for model in model_list:
                activity_inputs = DuckLakeCopyDataImportsActivityInputs(
                    team_id=inputs.team_id, job_id=inputs.job_id, model=model
                )
                copy_workload: DeltaTableSnapshotWorkload | None = await workflow.execute_activity(
                    copy_data_imports_to_ducklake_activity,
                    activity_inputs,
                    # TODO: Adjust timeouts based on table size?
                    start_to_close_timeout=dt.timedelta(minutes=30),
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )

                cleanup_inputs = None
                if model.staging_uri:
                    cleanup_inputs = DuckLakeDataImportsStagingCleanupInputs(
                        team_id=inputs.team_id,
                        staging_uri=model.staging_uri,
                        schema_id=model.source_schema_id,
                        job_id=inputs.job_id,
                    )
                    pending_staging_cleanup.append(cleanup_inputs)

                verification_results = await workflow.execute_activity(
                    verify_data_imports_ducklake_copy_activity,
                    activity_inputs,
                    start_to_close_timeout=dt.timedelta(minutes=10),
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

                for result in verification_results:
                    verification_status = "passed" if result.passed else "failed"
                    get_ducklake_copy_data_imports_verification_metric(
                        team_id=inputs.team_id,
                        schema_id=model.source_schema_id,
                        check_name=result.name,
                        status=verification_status,
                    ).add(1)

                failed_checks = [result for result in verification_results if not result.passed]
                if failed_checks:
                    failure_payload = [dataclasses.asdict(result) for result in failed_checks]
                    logger.error(
                        "DuckLake verification failed",
                        model_label=model.model_label,
                        failures=failure_payload,
                    )
                    raise ApplicationError(
                        f"DuckLake copy verification failed: {failure_payload}",
                        non_retryable=True,
                    )

                if copy_workload is not None:
                    _record_copy_workload(
                        team_id=inputs.team_id,
                        schema_id=model.source_schema_id,
                        workload=copy_workload,
                    )
                schema_finished_at = workflow.now()
                get_ducklake_copy_data_imports_last_success_metric(
                    team_id=inputs.team_id, schema_id=model.source_schema_id
                ).set(schema_finished_at.timestamp())

                completed_schema_id = schema_ids_by_value[model.source_schema_id]
                pending_schema_ids.remove(completed_schema_id)
                if track_source_job_state:
                    await _record_copy_terminal_source_job_state(
                        inputs=inputs,
                        schema_ids=[completed_schema_id],
                        status=ManagedWarehouseSourceJobStatus.COMPLETED,
                        started_at=workflow_started_at,
                        finished_at=schema_finished_at,
                    )

                if cleanup_inputs is not None:
                    await workflow.execute_activity(
                        cleanup_data_imports_staging_activity,
                        cleanup_inputs,
                        start_to_close_timeout=dt.timedelta(minutes=5),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                    pending_staging_cleanup.remove(cleanup_inputs)

            status = "completed"
        except Exception as error:
            if track_source_job_state:
                await _record_copy_source_job_state(
                    inputs=inputs,
                    schema_ids=list(pending_schema_ids),
                    status=ManagedWarehouseSourceJobStatus.FAILED,
                    started_at=workflow_started_at,
                    finished_at=workflow.now(),
                    latest_error=str(error),
                )
            raise
        finally:
            for cleanup_inputs in pending_staging_cleanup:
                try:
                    await workflow.execute_activity(
                        cleanup_data_imports_staging_activity,
                        cleanup_inputs,
                        start_to_close_timeout=dt.timedelta(minutes=5),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                except Exception:
                    logger.warning(
                        "Failed to clean up staging files",
                        staging_uri=cleanup_inputs.staging_uri,
                    )

            finished_at = workflow.now()
            duration_seconds = (finished_at - workflow_started_at).total_seconds()
            logger.info(
                "Finished DuckLakeCopyDataImportsWorkflow",
                status=status,
                duration_seconds=duration_seconds,
            )
            get_ducklake_copy_data_imports_finished_metric(team_id=inputs.team_id, status=status).add(1)
            get_ducklake_copy_data_imports_duration_metric(team_id=inputs.team_id, status=status).record(
                duration_seconds
            )
