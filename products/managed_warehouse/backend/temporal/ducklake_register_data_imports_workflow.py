from __future__ import annotations

import re
import json
import time
import uuid
import typing
import hashlib
import datetime as dt
import threading
import contextlib
import dataclasses
from collections.abc import Iterator, Sequence

from django.conf import settings
from django.db import close_old_connections

import psycopg
from psycopg import sql as psql
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
from posthog.temporal.common.metrics import ExecutionTimeRecorder

from products.data_warehouse.backend.facade.api import get_s3_client
from products.managed_warehouse.backend.client import make_duckgres_conninfo
from products.managed_warehouse.backend.common import (
    _get_org_id_for_team,
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
from products.managed_warehouse.backend.facade.feature_flags import DATA_WAREHOUSE_SCENE_FLAG
from products.managed_warehouse.backend.models import ManagedWarehouseSourceJob
from products.managed_warehouse.backend.storage import connect_to_duckgres, setup_duckgres_session
from products.managed_warehouse.backend.temporal.metrics import (
    get_ducklake_register_data_imports_bytes_metric,
    get_ducklake_register_data_imports_duration_metric,
    get_ducklake_register_data_imports_files_metric,
    get_ducklake_register_data_imports_finished_metric,
    get_ducklake_register_data_imports_last_success_metric,
    get_ducklake_register_data_imports_rows_metric,
    get_ducklake_register_data_imports_stale_metric,
    get_ducklake_register_data_imports_started_metric,
    record_ducklake_register_data_imports_stage_duration,
)
from products.managed_warehouse.backend.temporal.source_job_state import record_managed_warehouse_source_job_activity
from products.warehouse_sources.backend.facade.models import ExternalDataSchema

LOGGER = get_logger(__name__)
DATA_IMPORTS_GENERATIONS_PREFIX = "_imports"
DUCKLAKE_REGISTER_STAGE_DURATION_METRIC = "ducklake_register_data_imports_stage_duration"
S3_COPY_BATCH_SIZE = 16
# One CALL per batch. A generation-wide glob runs parquet_full_metadata on the
# DuckLake metadata connection and can stall there for large file counts.
_ADD_DATA_FILES_BATCH_SIZE = 200
_PARQUET_FILE_GLOB = "**/*.[pP][aA][rR][qQ][uU][eE][tT]"
_DUCKGRES_CANCEL_MARGIN = dt.timedelta(minutes=1)
_DUCKGRES_CANCEL_MAX_ATTEMPTS = 10
_DUCKGRES_CANCEL_RETRY_SECONDS = 0.5
_DUCKGRES_CANCEL_TIMEOUT_SECONDS = 5.0
_DUCKGRES_REGISTER_WORKER_OPTIONS = "-c duckgres.worker_cpu=4 -c duckgres.worker_memory=16Gi"
# Duckgres cancel fires one minute before this deadline. One attempt: a
# StartToClose timeout has an unknown catalog outcome, so a retry could race
# the original CALL.
_REGISTER_COPY_START_TO_CLOSE = dt.timedelta(hours=4)
_SOURCE_JOB_STATE_PATCH_ID = "ducklake-register-source-job-state-2026-08"
_CLEANUP_FINALIZER_PATCH_ID = "ducklake-register-cleanup-finalizer-2026-08"


def _register_source_job_update(
    *,
    inputs: DuckLakeRegisterDataImportsInputs,
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
        schema_ids=[inputs.schema_id],
        source_job_id=inputs.job_id,
        attempt_id=f"{inputs.job_id}:{_generation_token(inputs.prepared_queryable_folder)}",
        workflow_type=ManagedWarehouseSourceJobWorkflow.REGISTER,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        latest_error=latest_error,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
    )


async def _record_register_source_job_state(
    *,
    inputs: DuckLakeRegisterDataImportsInputs,
    status: ManagedWarehouseSourceJobStatus,
    started_at: dt.datetime,
    finished_at: dt.datetime | None = None,
    latest_error: str | None = None,
) -> None:
    await workflow.execute_activity(
        record_managed_warehouse_source_job_activity,
        _register_source_job_update(
            inputs=inputs,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            latest_error=latest_error,
        ),
        start_to_close_timeout=dt.timedelta(seconds=30),
        retry_policy=RetryPolicy(maximum_attempts=3),
    )


async def _record_register_terminal_source_job_state(
    *,
    inputs: DuckLakeRegisterDataImportsInputs,
    status: ManagedWarehouseSourceJobStatus,
    started_at: dt.datetime,
    finished_at: dt.datetime,
) -> None:
    try:
        await _record_register_source_job_state(
            inputs=inputs,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
        )
    except Exception:
        await _record_register_source_job_state(
            inputs=inputs,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
        )


def _stage_timer(*, stage: str, team_id: int, schema_id: str) -> ExecutionTimeRecorder:
    return ExecutionTimeRecorder(
        DUCKLAKE_REGISTER_STAGE_DURATION_METRIC,
        "Execution duration of one post-gate DuckLake data import registration stage.",
        {"stage": stage, "team_id": str(team_id), "schema_id": schema_id},
        log=True,
        histogram_recorder=record_ducklake_register_data_imports_stage_duration,
    )


def _bind_registration_activity_context(*, team_id: int, schema_id: str, job_id: str) -> None:
    identifiers = {"team_id": team_id, "schema_id": schema_id, "job_id": job_id}
    if activity.in_activity():
        workflow_id = activity.info().workflow_id
        if workflow_id is not None:
            identifiers["workflow_id"] = workflow_id
    bind_contextvars(**identifiers)


@dataclasses.dataclass
class DuckLakeRegisterDataImportsGateInputs:
    team_id: int


@dataclasses.dataclass
class DuckLakeRegisterDataImportsInputs:
    team_id: int
    job_id: str
    schema_id: uuid.UUID
    prepared_queryable_folder: str

    @property
    def properties_to_log(self) -> dict[str, typing.Any]:
        return {
            "team_id": self.team_id,
            "job_id": self.job_id,
            "schema_id": str(self.schema_id),
            "prepared_queryable_folder": self.prepared_queryable_folder,
        }


@dataclasses.dataclass
class DuckLakeRegisterDataImportsMetadata:
    source_schema_id: str
    prepared_queryable_folder: str
    prepared_source_uri: str
    landing_uri: str
    ducklake_schema_name: str
    ducklake_table_name: str


@dataclasses.dataclass(frozen=True)
class DuckLakeRegisterDataImportsActivityInputs:
    team_id: int
    job_id: str
    metadata: DuckLakeRegisterDataImportsMetadata
    # None only for histories recorded before the workflow minted the names;
    # those fall back to activity-local names (which the workflow cannot clean up).
    registration_table_names: RegistrationTableNames | None = None


@dataclasses.dataclass(frozen=True)
class DuckLakeRegisterCleanupInputs:
    team_id: int
    schema_name: str
    table_names: list[str]


class _StalePreparedGenerationError(Exception):
    pass


@activity.defn
async def ducklake_register_data_imports_gate_activity(inputs: DuckLakeRegisterDataImportsGateInputs) -> bool:
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind()

    try:
        team = await database_sync_to_async(Team.objects.only("organization_id").get)(id=inputs.team_id)
    except Team.DoesNotExist:
        await logger.aerror("Team does not exist when evaluating DuckLake data imports registration gate")
        return False

    organization_id = str(team.organization_id)
    try:
        flag_enabled = feature_enabled_or_false(
            DATA_WAREHOUSE_SCENE_FLAG,
            organization_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception as error:
        await logger.awarning("Failed to evaluate DuckLake data imports registration feature flag", error=str(error))
        capture_exception(error)
        return False

    if not flag_enabled:
        return False

    # The flag alone is not sufficient: registration resolves the team's schema through
    # the duckgres control plane, which only knows orgs with a provisioned server, so a
    # flag-enabled team in an unprovisioned org would fail the prepare activity with a
    # spurious "control plane unreachable" error. Dev mode has no DuckgresServer rows
    # (connections come from env vars), so the check applies only to real deployments.
    if is_dev_mode():
        return True

    server = await database_sync_to_async(get_duckgres_server_by_team_org)(inputs.team_id)
    if server is None:
        await logger.ainfo(
            "No DuckgresServer provisioned for team's organization; skipping DuckLake data imports registration"
        )
        return False

    return True


@activity.defn
async def prepare_ducklake_data_imports_registration_activity(
    inputs: DuckLakeRegisterDataImportsInputs,
) -> DuckLakeRegisterDataImportsMetadata | None:
    schema_id = str(inputs.schema_id)
    _bind_registration_activity_context(team_id=inputs.team_id, schema_id=schema_id, job_id=inputs.job_id)
    logger = LOGGER.bind(schema_id=str(inputs.schema_id), job_id=inputs.job_id)

    with _stage_timer(stage="prepare", team_id=inputs.team_id, schema_id=schema_id) as timer:
        if not _is_valid_queryable_folder(inputs.prepared_queryable_folder):
            raise ApplicationError(
                f"Invalid prepared queryable folder '{inputs.prepared_queryable_folder}'",
                non_retryable=True,
            )

        schema = await database_sync_to_async(ExternalDataSchema.objects.select_related("table", "source").get)(
            id=inputs.schema_id,
            team_id=inputs.team_id,
        )
        if schema.table is None or schema.table.queryable_folder != inputs.prepared_queryable_folder:
            timer.set_status("STALE")
            get_ducklake_register_data_imports_stale_metric(
                team_id=inputs.team_id, schema_id=schema_id, stage="prepare"
            ).add(1)
            await logger.ainfo(
                "Skipping stale prepared Parquet generation before registration",
                prepared_queryable_folder=inputs.prepared_queryable_folder,
            )
            return None

        prepared_source_uri = f"{settings.BUCKET_URL}/{schema.folder_path()}/{inputs.prepared_queryable_folder}"
        ducklake_schema_name = await database_sync_to_async(duckgres_data_imports_schema)(inputs.team_id)
        ducklake_table_name = await database_sync_to_async(duckgres_data_imports_table_name)(schema)
        landing_uri = await database_sync_to_async(_resolve_data_imports_landing_uri)(
            team_id=inputs.team_id,
            ducklake_schema_name=ducklake_schema_name,
            ducklake_table_name=ducklake_table_name,
            source_schema_id=str(inputs.schema_id),
            job_id=inputs.job_id,
            prepared_queryable_folder=inputs.prepared_queryable_folder,
        )
        return DuckLakeRegisterDataImportsMetadata(
            source_schema_id=str(schema.id),
            prepared_queryable_folder=inputs.prepared_queryable_folder,
            prepared_source_uri=prepared_source_uri,
            landing_uri=landing_uri,
            ducklake_schema_name=ducklake_schema_name,
            ducklake_table_name=ducklake_table_name,
        )


@activity.defn
def copy_and_register_ducklake_data_imports_activity(inputs: DuckLakeRegisterDataImportsActivityInputs) -> bool:
    activity_started_monotonic = time.monotonic()
    schema_id = inputs.metadata.source_schema_id
    _bind_registration_activity_context(team_id=inputs.team_id, schema_id=schema_id, job_id=inputs.job_id)
    logger = LOGGER.bind(
        schema_id=schema_id,
        job_id=inputs.job_id,
    )
    if not settings.TEST:
        close_old_connections()

    heartbeater = HeartbeaterSync(
        details=("ducklake_register_data_imports", inputs.metadata.source_schema_id),
        logger=logger,
    )
    with heartbeater:
        landing_uri = _generation_scoped_landing_uri(
            inputs.metadata.landing_uri,
            job_id=inputs.job_id,
            prepared_queryable_folder=inputs.metadata.prepared_queryable_folder,
        )
        with _stage_timer(stage="copy", team_id=inputs.team_id, schema_id=schema_id):
            landing_paths, copied_bytes = _copy_prepared_parquet_files(
                inputs.metadata.prepared_source_uri,
                landing_uri,
            )
        try:
            with _connect_to_duckgres_for_team(inputs.team_id) as conn:
                cancel_delay = _duckgres_cancel_delay(activity_started_monotonic)
                with _cancel_duckgres_query_after(conn, cancel_delay) as cancel_requested:
                    registered_rows = _register_prepared_parquet_files(
                        inputs,
                        conn,
                        landing_paths,
                        cancel_requested=cancel_requested,
                    )
        except _StalePreparedGenerationError:
            get_ducklake_register_data_imports_stale_metric(
                team_id=inputs.team_id, schema_id=schema_id, stage="publish"
            ).add(1)
            logger.info("Skipping stale prepared Parquet generation before catalog swap")
            return False

        get_ducklake_register_data_imports_files_metric(team_id=inputs.team_id, schema_id=schema_id).record(
            float(len(landing_paths))
        )
        get_ducklake_register_data_imports_rows_metric(team_id=inputs.team_id, schema_id=schema_id).record(
            float(registered_rows)
        )
        get_ducklake_register_data_imports_bytes_metric(team_id=inputs.team_id, schema_id=schema_id).record(
            float(copied_bytes)
        )

        logger.info(
            "Copied, verified, and registered prepared Parquet files in DuckLake",
            ducklake_table=f"{inputs.metadata.ducklake_schema_name}.{inputs.metadata.ducklake_table_name}",
            file_count=len(landing_paths),
            landing_uri=landing_uri,
        )
        return True


def _is_valid_queryable_folder(queryable_folder: str) -> bool:
    return bool(queryable_folder) and "/" not in queryable_folder and queryable_folder not in {".", ".."}


# `<table>__query_<epoch_seconds>[_<8 hex>]`, produced by prepare_s3_files_for_querying.
_GENERATION_SUFFIX_PATTERN = re.compile(r"__query_(\d+(?:_[0-9a-f]{8})?)$")


def _generation_token(prepared_queryable_folder: str) -> str:
    match = _GENERATION_SUFFIX_PATTERN.search(prepared_queryable_folder)
    if match:
        return match.group(1)
    # Folders predating the timestamped naming carry no generation, so derive a stable
    # token from the whole name to keep the workflow id unique per generation.
    return hashlib.sha256(prepared_queryable_folder.encode()).hexdigest()[:12]


def build_register_data_imports_workflow_id(*, team_id: int, schema_id: str) -> str:
    """Workflow id for one in-flight registration per schema.

    Callers treat WorkflowAlreadyStartedError as "already running" and drop the
    trigger. Job and generation stay out of the id so a later sync cannot start
    until this run finishes. The next import after that can start and pick up
    the latest prepared folder.
    """
    return f"ducklake-register-data-imports-{team_id}-{schema_id}"


def _resolve_data_imports_landing_uri(
    *,
    team_id: int,
    ducklake_schema_name: str,
    ducklake_table_name: str,
    source_schema_id: str,
    job_id: str,
    prepared_queryable_folder: str,
) -> str:
    if is_dev_mode():
        bucket = get_config().get("DUCKLAKE_BUCKET")
    else:
        server = get_duckgres_server_by_team_org(team_id)
        bucket = server.bucket if server is not None else None
    if not bucket:
        raise ApplicationError(f"No S3 bucket configured for team {team_id}", non_retryable=True)

    safe_job_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(job_id))
    job_landing_uri = (
        f"s3://{bucket}/{ducklake_schema_name}/{ducklake_table_name}/"
        f"{DATA_IMPORTS_GENERATIONS_PREFIX}/{source_schema_id}/{safe_job_id}"
    )
    return _generation_scoped_landing_uri(
        job_landing_uri,
        job_id=job_id,
        prepared_queryable_folder=prepared_queryable_folder,
    )


def _generation_scoped_landing_uri(
    landing_uri: str,
    *,
    job_id: str,
    prepared_queryable_folder: str,
) -> str:
    normalized_uri = landing_uri.rstrip("/")
    safe_job_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(job_id))
    generation_token = _generation_token(prepared_queryable_folder)
    generation_suffix = f"/{safe_job_id}/{generation_token}"
    if normalized_uri.endswith(generation_suffix):
        return normalized_uri
    if normalized_uri.endswith(f"/{safe_job_id}"):
        # Activity inputs can outlive worker deployments, so accept a recorded job-scoped URI.
        return f"{normalized_uri}/{generation_token}"
    raise ApplicationError("DuckLake landing URI does not match the registration job", non_retryable=True)


def _copy_prepared_parquet_files(source_uri: str, landing_uri: str) -> tuple[list[str], int]:
    source_prefix = source_uri.removeprefix("s3://").rstrip("/")
    landing_prefix = landing_uri.removeprefix("s3://").rstrip("/")
    s3 = get_s3_client()
    found = s3.find(source_prefix, detail=True)
    source_paths = list(found.keys()) if isinstance(found, dict) else list(found)
    parquet_paths = sorted(str(path) for path in source_paths if str(path).lower().endswith(".parquet"))
    if not parquet_paths:
        raise ApplicationError(f"No prepared Parquet files found under {source_uri}", non_retryable=True)

    source_copy_paths: list[str] = []
    landing_copy_paths: list[str] = []
    landing_paths: list[str] = []
    for source_path_value in parquet_paths:
        source_path = source_path_value.removeprefix("s3://")
        relative_path = source_path.removeprefix(f"{source_prefix}/")
        if relative_path == source_path or relative_path.startswith("../"):
            raise ApplicationError(f"Prepared file escaped source prefix: {source_path}", non_retryable=True)
        landing_path = f"{landing_prefix}/{relative_path}"
        source_copy_paths.append(source_path)
        landing_copy_paths.append(landing_path)
        landing_paths.append(f"s3://{landing_path}")

    s3.copy(source_copy_paths, landing_copy_paths, batch_size=S3_COPY_BATCH_SIZE)

    copied_bytes = 0
    if isinstance(found, dict):
        copied_bytes = sum(
            int(details.get("Size", 0))
            for path, details in found.items()
            if str(path).lower().endswith(".parquet") and isinstance(details, dict)
        )

    return landing_paths, copied_bytes


def _current_prepared_queryable_folder(inputs: DuckLakeRegisterDataImportsActivityInputs) -> str | None:
    try:
        schema = ExternalDataSchema.objects.select_related("table").get(
            id=inputs.metadata.source_schema_id,
            team_id=inputs.team_id,
        )
    except ExternalDataSchema.DoesNotExist:
        return None
    if schema.table is None:
        return None
    return schema.table.queryable_folder


def _prepared_generation_is_current(inputs: DuckLakeRegisterDataImportsActivityInputs) -> bool:
    return _current_prepared_queryable_folder(inputs) == inputs.metadata.prepared_queryable_folder


def _register_completed_for_generation(*, team_id: int, schema_id: str, prepared_queryable_folder: str) -> bool:
    try:
        schema_uuid = uuid.UUID(schema_id)
    except ValueError:
        return False
    token = _generation_token(prepared_queryable_folder)
    return (
        ManagedWarehouseSourceJob.objects.for_team(team_id)
        .filter(
            schema_id=schema_uuid,
            workflow_type=ManagedWarehouseSourceJob.WorkflowType.REGISTER,
            status=ManagedWarehouseSourceJob.Status.COMPLETED,
            attempt_id__endswith=f":{token}",
        )
        .exists()
    )


def _should_publish_prepared_generation(inputs: DuckLakeRegisterDataImportsActivityInputs) -> bool:
    # A newer folder appearing mid-run is the common case for large generations.
    # Aborting after ducklake_add_data_files leaves the live table unchanged and
    # the next run can lose the same race. Publish this verified snapshot unless
    # the newer folder has already landed, so the live table does not move backward.
    if _prepared_generation_is_current(inputs):
        return True
    current_folder = _current_prepared_queryable_folder(inputs)
    if current_folder is None:
        return False
    return not _register_completed_for_generation(
        team_id=inputs.team_id,
        schema_id=inputs.metadata.source_schema_id,
        prepared_queryable_folder=current_folder,
    )


@contextlib.contextmanager
def _connect_to_duckgres_for_team(team_id: int) -> Iterator[psycopg.Connection]:
    if is_dev_mode():
        conninfo = make_duckgres_conninfo(team_id, application_name="ducklake-register")
        with psycopg.connect(conninfo, autocommit=True, options=_DUCKGRES_REGISTER_WORKER_OPTIONS) as conn:
            yield conn
        return

    organization_id = _get_org_id_for_team(team_id)
    server = get_duckgres_server_for_organization(organization_id)
    if server is None:
        raise ApplicationError(f"No DuckgresServer configured for team {team_id}", non_retryable=True)
    with connect_to_duckgres(
        server,
        application_name="ducklake-register",
        options=_DUCKGRES_REGISTER_WORKER_OPTIONS,
    ) as conn:
        yield conn


def _duckgres_cancel_delay(activity_started_monotonic: float) -> float | None:
    try:
        start_to_close_timeout = activity.info().start_to_close_timeout
    except RuntimeError:
        return None
    if start_to_close_timeout is None:
        return None

    elapsed = time.monotonic() - activity_started_monotonic
    return max(0.0, start_to_close_timeout.total_seconds() - elapsed - _DUCKGRES_CANCEL_MARGIN.total_seconds())


@contextlib.contextmanager
def _cancel_duckgres_query_after(
    conn: psycopg.Connection,
    delay_seconds: float | None,
) -> Iterator[threading.Event]:
    cancel_requested = threading.Event()
    if delay_seconds is None:
        yield cancel_requested
        return
    if delay_seconds <= 0:
        raise TimeoutError("Duckgres registration started too close to the Temporal activity deadline")

    stop_canceling = threading.Event()

    def cancel_query() -> None:
        if stop_canceling.is_set():
            return
        cancel_requested.set()
        LOGGER.warning("Canceling Duckgres query before Temporal activity timeout")
        cancellation_failure_logged = False
        for attempt in range(_DUCKGRES_CANCEL_MAX_ATTEMPTS):
            if stop_canceling.is_set():
                return
            try:
                conn.cancel_safe(timeout=_DUCKGRES_CANCEL_TIMEOUT_SECONDS)
            except Exception:
                if not cancellation_failure_logged:
                    LOGGER.exception("Failed to cancel Duckgres query before Temporal activity timeout")
                    cancellation_failure_logged = True
            if attempt == _DUCKGRES_CANCEL_MAX_ATTEMPTS - 1:
                LOGGER.error("Stopped retrying Duckgres query cancellation before Temporal activity timeout")
                return
            if stop_canceling.wait(_DUCKGRES_CANCEL_RETRY_SECONDS):
                return

    timer = threading.Timer(delay_seconds, cancel_query)
    timer.daemon = True
    timer.start()
    try:
        yield cancel_requested
    finally:
        stop_canceling.set()
        timer.cancel()
        timer.join(timeout=_DUCKGRES_CANCEL_TIMEOUT_SECONDS + 1)


def _raise_if_duckgres_cancel_requested(cancel_requested: threading.Event | None) -> None:
    if cancel_requested is not None and cancel_requested.is_set():
        raise TimeoutError("Duckgres registration reached the Temporal activity deadline")


def _add_data_files_path_batches(landing_paths: Sequence[str], *, batch_size: int | None = None) -> list[list[str]]:
    resolved_batch_size = _ADD_DATA_FILES_BATCH_SIZE if batch_size is None else batch_size
    if resolved_batch_size < 1:
        raise ValueError("add_data_files batch size must be at least 1")
    return [
        list(landing_paths[index : index + resolved_batch_size])
        for index in range(0, len(landing_paths), resolved_batch_size)
    ]


def _duckdb_varchar_list_literal(values: Sequence[str]) -> psql.Composed:
    return psql.SQL("[{}]").format(psql.SQL(", ").join(psql.Literal(value) for value in values))


def _register_prepared_parquet_files(
    inputs: DuckLakeRegisterDataImportsActivityInputs,
    conn: psycopg.Connection,
    landing_paths: list[str],
    *,
    cancel_requested: threading.Event | None = None,
) -> int:
    schema_name = inputs.metadata.ducklake_schema_name
    table_name = inputs.metadata.ducklake_table_name
    registration_names = inputs.registration_table_names or _new_registration_table_names()
    landing_uri = _generation_scoped_landing_uri(
        inputs.metadata.landing_uri,
        job_id=inputs.job_id,
        prepared_queryable_folder=inputs.metadata.prepared_queryable_folder,
    )
    parquet_glob = psql.Literal(f"{landing_uri}/{_PARQUET_FILE_GLOB}")
    partition_columns = _hive_partition_columns(landing_uri, landing_paths)

    _raise_if_duckgres_cancel_requested(cancel_requested)
    setup_duckgres_session(conn, extensions=("ducklake", "httpfs"))
    shadow_is_published = False
    publish_attempted = False
    try:
        with _stage_timer(stage="register", team_id=inputs.team_id, schema_id=inputs.metadata.source_schema_id):
            _raise_if_duckgres_cancel_requested(cancel_requested)
            conn.execute(psql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(psql.Identifier(schema_name)))
            _raise_if_duckgres_cancel_requested(cancel_requested)
            conn.execute(
                psql.SQL(
                    "CREATE TABLE {}.{} AS SELECT * FROM "
                    "read_parquet({}, union_by_name=true, hive_partitioning=true) LIMIT 0"
                ).format(
                    psql.Identifier(schema_name),
                    psql.Identifier(registration_names.shadow_name),
                    parquet_glob,
                )
            )
            if partition_columns:
                _raise_if_duckgres_cancel_requested(cancel_requested)
                conn.execute(
                    psql.SQL("ALTER TABLE {}.{} SET PARTITIONED BY ({})").format(
                        psql.Identifier(schema_name),
                        psql.Identifier(registration_names.shadow_name),
                        psql.SQL(", ").join(psql.Identifier(column) for column in partition_columns),
                    )
                )
            _raise_if_duckgres_cancel_requested(cancel_requested)
            for path_batch in _add_data_files_path_batches(landing_paths):
                _raise_if_duckgres_cancel_requested(cancel_requested)
                conn.execute(
                    psql.SQL(
                        "CALL ducklake_add_data_files({}, {}, {}, schema => {}, "
                        "allow_missing => true, hive_partitioning => true)"
                    ).format(
                        psql.Literal("ducklake"),
                        psql.Literal(registration_names.shadow_name),
                        _duckdb_varchar_list_literal(path_batch),
                        psql.Literal(schema_name),
                    )
                )

        with _stage_timer(stage="verify", team_id=inputs.team_id, schema_id=inputs.metadata.source_schema_id):
            _raise_if_duckgres_cancel_requested(cancel_requested)
            source_row = conn.execute(
                psql.SQL("SELECT count(*) FROM read_parquet({}, union_by_name=true, hive_partitioning=true)").format(
                    parquet_glob
                )
            ).fetchone()
            _raise_if_duckgres_cancel_requested(cancel_requested)
            registered_row = conn.execute(
                psql.SQL("SELECT count(*) FROM {}.{}").format(
                    psql.Identifier(schema_name),
                    psql.Identifier(registration_names.shadow_name),
                )
            ).fetchone()
            source_count = int(source_row[0]) if source_row else 0
            registered_count = int(registered_row[0]) if registered_row else 0
            if source_count != registered_count:
                raise ApplicationError(
                    "DuckLake prepared-file registration row count mismatch: "
                    f"source={source_count}, registered={registered_count}",
                    non_retryable=True,
                )

        generation_is_stale = False
        with _stage_timer(stage="publish", team_id=inputs.team_id, schema_id=inputs.metadata.source_schema_id) as timer:
            _raise_if_duckgres_cancel_requested(cancel_requested)
            if _should_publish_prepared_generation(inputs):
                _raise_if_duckgres_cancel_requested(cancel_requested)
                publish_attempted = True
                # Keep this transaction limited to publication. DuckLake flushes staged file
                # metadata at commit, so including registration makes the catalog commit expensive.
                with conn.transaction():
                    conn.execute(
                        psql.SQL("ALTER TABLE IF EXISTS {}.{} RENAME TO {}").format(
                            psql.Identifier(schema_name),
                            psql.Identifier(table_name),
                            psql.Identifier(registration_names.previous_name),
                        )
                    )
                    _raise_if_duckgres_cancel_requested(cancel_requested)
                    conn.execute(
                        psql.SQL("ALTER TABLE {}.{} RENAME TO {}").format(
                            psql.Identifier(schema_name),
                            psql.Identifier(registration_names.shadow_name),
                            psql.Identifier(table_name),
                        )
                    )
                shadow_is_published = True
            else:
                timer.set_status("STALE")
                generation_is_stale = True

        if generation_is_stale:
            raise _StalePreparedGenerationError

        return registered_count
    finally:
        cleanup_names = [registration_names.previous_name] if publish_attempted else []
        if not shadow_is_published:
            cleanup_names.insert(0, registration_names.shadow_name)
        _cleanup_registration_tables(conn, schema_name, cleanup_names)


@dataclasses.dataclass(frozen=True, kw_only=True)
class RegistrationTableNames:
    shadow_name: str
    previous_name: str


def registration_table_names_from_token(attempt_token: str) -> RegistrationTableNames:
    return RegistrationTableNames(
        shadow_name=f"__ph_register_{attempt_token}",
        previous_name=f"__ph_previous_{attempt_token}",
    )


def _new_registration_table_names() -> RegistrationTableNames:
    return registration_table_names_from_token(uuid.uuid4().hex)


_CLEANUP_DROP_ATTEMPTS = 3
_CLEANUP_DROP_RETRY_SECONDS = 2.0


def _drop_registration_table(conn: psycopg.Connection, schema_name: str, table_name: str) -> None:
    conn.execute(
        psql.SQL("DROP TABLE IF EXISTS {}.{}").format(
            psql.Identifier(schema_name),
            psql.Identifier(table_name),
        )
    )


def _cleanup_registration_tables(conn: psycopg.Connection, schema_name: str, table_names: list[str]) -> None:
    # Best-effort: this runs in the register `finally`, so raising here would mask
    # the in-flight exception. A table left behind is picked up by the workflow's
    # cleanup finalizer activity, which retries with a fresh connection.
    #
    # A dead connection cannot recover, so retrying the drop or reporting the
    # failure adds no value: the register activity already failed on the transport,
    # and the finalizer retries the drop with a fresh connection.
    if conn.closed:
        LOGGER.warning(
            "Skipped DuckLake registration cleanup on a closed connection; the workflow cleanup finalizer will retry",
            schema_name=schema_name,
        )
        return
    for table_name in table_names:
        for attempt in range(1, _CLEANUP_DROP_ATTEMPTS + 1):
            try:
                _drop_registration_table(conn, schema_name, table_name)
                break
            except (psycopg.OperationalError, psycopg.InterfaceError):
                LOGGER.warning(
                    "Aborted DuckLake registration cleanup on a broken connection; the workflow cleanup finalizer will retry",
                    table_name=f"{schema_name}.{table_name}",
                )
                return
            except Exception as error:
                if attempt == _CLEANUP_DROP_ATTEMPTS:
                    LOGGER.error(
                        "Failed to clean up DuckLake registration table; the workflow cleanup finalizer will retry",
                        table_name=f"{schema_name}.{table_name}",
                        exc_info=True,
                    )
                    capture_exception(error)
                else:
                    time.sleep(_CLEANUP_DROP_RETRY_SECONDS * attempt)


# A registration attempt's tables can live at most 4h (the copy activity's
# start_to_close) plus ~25min of finalizer retries; anything older under the
# registration naming pattern is an orphan from a path no finalizer could reach
# (workflow terminate, pre-patch histories, cleanup retry exhaustion). The
# missing-snapshot rule below additionally requires every deployment's snapshot
# retention to exceed this age, or an in-flight attempt's table could be swept.
_SWEEP_MIN_AGE = dt.timedelta(hours=6)
# Each drop is its own catalog commit; the batch is sized so a full sweep fits
# comfortably inside the finalizer's start_to_close on a contended catalog.
# Every registration run sweeps again, so a backlog drains across runs.
_SWEEP_BATCH_LIMIT = 15
_REGISTRATION_TABLE_REGEX = "^__ph_(register|previous)_[0-9a-f]{32}$"


def _sweep_query(schema_name: str) -> psql.Composed:
    # A missing snapshot row means the table's creation snapshot already expired,
    # so it is strictly older than any age guard: treat it as stale, not unknown.
    return psql.SQL(
        "SELECT t.table_name "
        "FROM __ducklake_metadata_ducklake.ducklake_table t "
        "JOIN __ducklake_metadata_ducklake.ducklake_schema s "
        "  ON s.schema_id = t.schema_id AND s.end_snapshot IS NULL "
        "LEFT JOIN __ducklake_metadata_ducklake.ducklake_snapshot sn "
        "  ON sn.snapshot_id = t.begin_snapshot "
        "WHERE t.end_snapshot IS NULL "
        "  AND s.schema_name = {} "
        "  AND t.table_name ~ {} "
        # DuckDB does not infer intervals from bare string literals; the
        # explicit CAST is what makes the age guard bind at all.
        "  AND (sn.snapshot_id IS NULL OR CAST(sn.snapshot_time AS TIMESTAMPTZ) < now() - CAST({} AS INTERVAL)) "
        "LIMIT {}"
    ).format(
        psql.Literal(schema_name),
        psql.Literal(_REGISTRATION_TABLE_REGEX),
        psql.Literal(f"{int(_SWEEP_MIN_AGE.total_seconds())} seconds"),
        psql.Literal(_SWEEP_BATCH_LIMIT),
    )


def _sweep_stale_registration_tables(conn: psycopg.Connection, schema_name: str) -> list[str]:
    rows = conn.execute(_sweep_query(schema_name)).fetchall()
    swept: list[str] = []
    for (table_name,) in rows:
        _drop_registration_table(conn, schema_name, table_name)
        swept.append(table_name)
    return swept


@activity.defn
def cleanup_ducklake_registration_tables_activity(inputs: DuckLakeRegisterCleanupInputs) -> None:
    """Drop this attempt's registration tables, however the register activity ended.

    Runs as a workflow-level finalizer so a worker crash, OOM, or activity timeout
    cannot orphan the shadow/previous tables: the workflow replays and re-schedules
    this activity until the drops land. Attempt-scoped uuid names plus
    ``DROP TABLE IF EXISTS`` make it idempotent and collision-free with any other
    registration attempt. Afterwards it sweeps stale registration tables in the
    same schema, so each run that reaches registration also disposes of orphans
    no finalizer could reach; the age guard keeps concurrent attempts' young
    tables safe.
    """
    bind_contextvars(team_id=inputs.team_id)
    logger = LOGGER.bind(schema_name=inputs.schema_name)
    if not settings.TEST:
        close_old_connections()

    with _connect_to_duckgres_for_team(inputs.team_id) as conn:
        setup_duckgres_session(conn, extensions=("ducklake",))
        for table_name in inputs.table_names:
            _drop_registration_table(conn, inputs.schema_name, table_name)
        logger.info("Cleaned up DuckLake registration tables", table_names=inputs.table_names)
        try:
            swept = _sweep_stale_registration_tables(conn, inputs.schema_name)
        except Exception as error:
            # The sweep is opportunistic: this attempt's own tables are already
            # dropped, and the next registration in this schema sweeps again.
            logger.warning("Stale registration table sweep failed", error=str(error))
            capture_exception(error)
        else:
            if swept:
                logger.info("Swept stale DuckLake registration tables", table_names=swept)


def _hive_partition_columns(landing_uri: str, landing_paths: list[str]) -> list[str]:
    landing_prefix = landing_uri.rstrip("/") + "/"
    columns: list[str] = []
    for landing_path in landing_paths:
        relative_path = landing_path.removeprefix(landing_prefix)
        for segment in relative_path.split("/")[:-1]:
            column, separator, _ = segment.partition("=")
            if separator and column and column not in columns:
                columns.append(column)
    return columns


@workflow.defn(name="ducklake-register.data-imports")
class DuckLakeRegisterDataImportsWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> DuckLakeRegisterDataImportsInputs:
        loaded = json.loads(inputs[0])
        schema_id = loaded["schema_id"]
        return DuckLakeRegisterDataImportsInputs(
            team_id=loaded["team_id"],
            job_id=loaded["job_id"],
            schema_id=uuid.UUID(schema_id) if isinstance(schema_id, str) else schema_id,
            prepared_queryable_folder=loaded["prepared_queryable_folder"],
        )

    @workflow.run
    async def run(self, inputs: DuckLakeRegisterDataImportsInputs) -> None:
        logger = LOGGER.bind(**inputs.properties_to_log)
        if workflow.in_workflow():
            logger = logger.bind(workflow_id=workflow.info().workflow_id)
        workflow_started_at = workflow.now()
        logger.info("Starting DuckLakeRegisterDataImportsWorkflow")

        should_register = await workflow.execute_activity(
            ducklake_register_data_imports_gate_activity,
            DuckLakeRegisterDataImportsGateInputs(team_id=inputs.team_id),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        if not should_register:
            logger.info("DuckLake data imports registration gated off (flag disabled or no DuckgresServer)")
            return

        track_source_job_state = workflow.patched(_SOURCE_JOB_STATE_PATCH_ID)
        schema_id = str(inputs.schema_id)
        get_ducklake_register_data_imports_started_metric(team_id=inputs.team_id, schema_id=schema_id).add(1)
        status = "failed"
        try:
            if track_source_job_state:
                await _record_register_source_job_state(
                    inputs=inputs,
                    status=ManagedWarehouseSourceJobStatus.RUNNING,
                    started_at=workflow_started_at,
                )
            metadata = await workflow.execute_activity(
                prepare_ducklake_data_imports_registration_activity,
                inputs,
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if metadata is None:
                status = "stale"
                if track_source_job_state:
                    await _record_register_terminal_source_job_state(
                        inputs=inputs,
                        status=ManagedWarehouseSourceJobStatus.STALE,
                        started_at=workflow_started_at,
                        finished_at=workflow.now(),
                    )
                logger.info("Prepared Parquet generation is stale; nothing to register")
                return

            # Minting the names in the workflow puts them in history, so the cleanup
            # finalizer can drop them even when the register activity's process dies
            # before its own finally runs and leaves the shadow/previous tables behind.
            registration_table_names: RegistrationTableNames | None = None
            if workflow.patched(_CLEANUP_FINALIZER_PATCH_ID):
                registration_table_names = registration_table_names_from_token(workflow.uuid4().hex)

            activity_inputs = DuckLakeRegisterDataImportsActivityInputs(
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                metadata=metadata,
                registration_table_names=registration_table_names,
            )
            try:
                copy_applied = await workflow.execute_activity(
                    copy_and_register_ducklake_data_imports_activity,
                    activity_inputs,
                    start_to_close_timeout=_REGISTER_COPY_START_TO_CLOSE,
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            finally:
                if registration_table_names is not None:
                    try:
                        await workflow.execute_activity(
                            cleanup_ducklake_registration_tables_activity,
                            DuckLakeRegisterCleanupInputs(
                                team_id=inputs.team_id,
                                schema_name=metadata.ducklake_schema_name,
                                table_names=[
                                    registration_table_names.shadow_name,
                                    registration_table_names.previous_name,
                                ],
                            ),
                            start_to_close_timeout=dt.timedelta(minutes=2),
                            # Patient on purpose: the drops are idempotent and a leaked
                            # table is permanent, so ~25 minutes of retries rides out a
                            # duckgres outage (the correlated cause of cleanup failing).
                            retry_policy=RetryPolicy(
                                maximum_attempts=10,
                                initial_interval=dt.timedelta(seconds=5),
                                backoff_coefficient=2.0,
                                maximum_interval=dt.timedelta(minutes=5),
                            ),
                        )
                    except Exception:
                        # Cleanup failure must not mask the register outcome; leftover
                        # tables are visible via the __ph_register_/__ph_previous_ naming.
                        logger.exception("DuckLake registration table cleanup failed after retries")
            if not copy_applied:
                status = "stale"
                if track_source_job_state:
                    await _record_register_terminal_source_job_state(
                        inputs=inputs,
                        status=ManagedWarehouseSourceJobStatus.STALE,
                        started_at=workflow_started_at,
                        finished_at=workflow.now(),
                    )
                logger.info("Prepared Parquet generation became stale; registration skipped")
                return

            status = "completed"
            if track_source_job_state:
                await _record_register_terminal_source_job_state(
                    inputs=inputs,
                    status=ManagedWarehouseSourceJobStatus.COMPLETED,
                    started_at=workflow_started_at,
                    finished_at=workflow.now(),
                )
        except Exception as error:
            if track_source_job_state and status == "failed":
                await _record_register_source_job_state(
                    inputs=inputs,
                    status=ManagedWarehouseSourceJobStatus.FAILED,
                    started_at=workflow_started_at,
                    finished_at=workflow.now(),
                    latest_error=str(error),
                )
            raise
        finally:
            finished_at = workflow.now()
            duration_seconds = (finished_at - workflow_started_at).total_seconds()
            logger.info(
                "Finished DuckLakeRegisterDataImportsWorkflow",
                status=status,
                duration_seconds=duration_seconds,
            )
            get_ducklake_register_data_imports_finished_metric(
                team_id=inputs.team_id, schema_id=schema_id, status=status
            ).add(1)
            get_ducklake_register_data_imports_duration_metric(
                team_id=inputs.team_id, schema_id=schema_id, status=status
            ).record(duration_seconds)
            if status == "completed":
                get_ducklake_register_data_imports_last_success_metric(team_id=inputs.team_id, schema_id=schema_id).set(
                    finished_at.timestamp()
                )
