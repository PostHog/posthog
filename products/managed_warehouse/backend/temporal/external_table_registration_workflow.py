from __future__ import annotations

import json
import time
import uuid
import hashlib
import datetime as dt
import threading
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone

from psycopg import sql
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.dataclasses import frozen
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_logger

from products.data_warehouse.backend.facade.api import get_s3_client
from products.managed_warehouse.backend.common import get_config, get_duckgres_server_by_team_org, is_dev_mode
from products.managed_warehouse.backend.external_tables import external_table_sync_feature_enabled
from products.managed_warehouse.backend.models import ManagedWarehouseExternalTable
from products.managed_warehouse.backend.storage import setup_duckgres_session
from products.managed_warehouse.backend.temporal.ducklake_register_data_imports_workflow import (
    DuckLakeRegisterCleanupInputs,
    DuckLakeRegisterDataImportsGateInputs,
    _add_data_files_path_batches,
    _cancel_duckgres_query_after,
    _connect_to_duckgres_for_team,
    _duckgres_cancel_delay,
    cleanup_ducklake_registration_tables_activity,
    ducklake_register_data_imports_gate_activity,
    registration_table_names_from_token,
)
from products.managed_warehouse.backend.temporal.external_delta_snapshot import prepare_delta_snapshot
from products.managed_warehouse.backend.temporal.parquet_registration import ParquetRegistration
from products.warehouse_sources.backend.facade.external_delta import get_external_delta_table

if TYPE_CHECKING:
    import psycopg

LOGGER = get_logger(__name__)


@frozen
class ExternalTableRegistrationInputs:
    team_id: int
    table_id: uuid.UUID


@frozen
class ExternalTableRegistrationAttempt:
    team_id: int
    table_id: uuid.UUID
    attempt_token: str


@frozen
class PublishedDeltaSnapshot:
    table_id: str
    fingerprint: str
    delta_table_id: str
    version: int

    def to_comment(self) -> str:
        return json.dumps(
            {
                "external_table_id": self.table_id,
                "fingerprint": self.fingerprint,
                "delta_table_id": self.delta_table_id,
                "delta_version": self.version,
            },
            separators=(",", ":"),
        )


def read_published_snapshot(
    conn: psycopg.Connection, registration: ParquetRegistration
) -> PublishedDeltaSnapshot | None:
    row = conn.execute(
        sql.SQL(
            "SELECT comment FROM duckdb_tables() "
            "WHERE database_name = current_database() AND schema_name = {} AND table_name = {}"
        ).format(sql.Literal(registration.schema_name), sql.Literal(registration.table_name))
    ).fetchone()
    if row is None:
        return None
    try:
        marker = json.loads(row[0])
        version = marker["delta_version"]
        if type(version) is not int or version < 0:
            raise ValueError("Invalid Delta version")
        fields = [marker[key] for key in ("external_table_id", "fingerprint", "delta_table_id")]
        if not all(isinstance(field, str) and field for field in fields):
            raise ValueError("Invalid snapshot identity")
        return PublishedDeltaSnapshot(
            table_id=fields[0], fingerprint=fields[1], delta_table_id=fields[2], version=version
        )
    except (ValueError, TypeError, KeyError) as error:
        raise ApplicationError(
            "The destination table has no valid external snapshot marker", non_retryable=True
        ) from error


def validate_snapshot_identity(current: PublishedDeltaSnapshot, candidate: PublishedDeltaSnapshot) -> None:
    if (
        current.table_id != candidate.table_id
        or current.fingerprint != candidate.fingerprint
        or current.delta_table_id != candidate.delta_table_id
    ):
        raise ApplicationError("The registered Delta table identity changed", non_retryable=True)


def publish_external_snapshot(
    conn: psycopg.Connection,
    registration: ParquetRegistration,
    candidate: PublishedDeltaSnapshot,
    cancel_requested: threading.Event | None = None,
) -> PublishedDeltaSnapshot:
    with conn.transaction():
        current = read_published_snapshot(conn, registration)
        if current is not None:
            validate_snapshot_identity(current, candidate)
            if current.version >= candidate.version:
                return current
        registration.publish(conn, cancel_requested)
        # Keep the watermark in the same catalog transaction as the table swap so a lost
        # commit response can be recovered without publishing an older snapshot.
        registration.check_cancellation(cancel_requested)
        conn.execute(
            sql.SQL("COMMENT ON TABLE {}.{} IS {}").format(
                sql.Identifier(registration.schema_name),
                sql.Identifier(registration.table_name),
                sql.Literal(candidate.to_comment()),
            )
        )
    return candidate


def _record_published_snapshot(team_id: int, table_id: uuid.UUID, published: PublishedDeltaSnapshot) -> None:
    ManagedWarehouseExternalTable.objects.for_team(team_id).filter(
        Q(published_version__isnull=True) | Q(published_version__lte=published.version),
        table_id=table_id,
        source_fingerprint=published.fingerprint,
    ).update(
        delta_table_id=published.delta_table_id,
        published_version=published.version,
        last_synced_at=timezone.now(),
        latest_error=None,
    )


def _register_external_table(inputs: ExternalTableRegistrationAttempt) -> bool:
    started = time.monotonic()
    import deltalake  # noqa: PLC0415 -- keeps the optional Delta reader off the worker import path

    enrolled = (
        ManagedWarehouseExternalTable.objects.for_team(inputs.team_id)
        .filter(table_id=inputs.table_id, enabled=True)
        .first()
    )
    if enrolled is None or not external_table_sync_feature_enabled(inputs.team_id):
        return False
    source = get_external_delta_table(inputs.team_id, inputs.table_id, with_credentials=True)
    if source.fingerprint != enrolled.source_fingerprint:
        raise ApplicationError("The enrolled external table configuration changed", non_retryable=True)
    options = dict(source.storage_options)
    if is_dev_mode():
        from products.managed_warehouse.backend.storage import (
            get_deltalake_storage_options,  # noqa: PLC0415 -- only needed for local storage
        )

        options = get_deltalake_storage_options(team_id=inputs.team_id) | options
    table = deltalake.DeltaTable(source.uri, storage_options=options)
    candidate = PublishedDeltaSnapshot(
        table_id=str(inputs.table_id),
        fingerprint=source.fingerprint,
        delta_table_id=str(table.metadata().id),
        version=table.version(),
    )
    if enrolled.delta_table_id is not None and enrolled.delta_table_id != candidate.delta_table_id:
        raise ApplicationError("The registered Delta table identity changed", non_retryable=True)
    server = get_duckgres_server_by_team_org(inputs.team_id) if not is_dev_mode() else None
    bucket = get_config().get("DUCKLAKE_BUCKET") if is_dev_mode() else (server.bucket if server else None)
    if not bucket:
        raise ApplicationError("No warehouse bucket is configured", non_retryable=True)
    landing_uri = (
        f"s3://{bucket}/{enrolled.warehouse_schema}/{enrolled.warehouse_table}/"
        f"_external/{enrolled.id}/{hashlib.sha256(candidate.delta_table_id.encode()).hexdigest()}/"
        f"{candidate.version}/{inputs.attempt_token}"
    )
    names = registration_table_names_from_token(inputs.attempt_token)
    registration = ParquetRegistration(
        schema_name=enrolled.warehouse_schema,
        table_name=enrolled.warehouse_table,
        shadow_name=names.shadow_name,
        previous_name=names.previous_name,
        parquet_glob=f"{landing_uri}/*.parquet",
    )
    with _connect_to_duckgres_for_team(inputs.team_id) as conn:
        with _cancel_duckgres_query_after(conn, _duckgres_cancel_delay(started)) as cancel_requested:
            setup_duckgres_session(conn, extensions=("ducklake", "httpfs"))
            current = read_published_snapshot(conn, registration)
            if current is not None:
                validate_snapshot_identity(current, candidate)
                if current.version >= candidate.version:
                    _record_published_snapshot(inputs.team_id, inputs.table_id, current)
                    return False
            snapshot = prepare_delta_snapshot(table, get_s3_client(), landing_uri, cancel_requested)
            registration.check_cancellation(cancel_requested)
            registration.prepare(conn, _add_data_files_path_batches(snapshot.paths), (), cancel_requested)
            registered_count = registration.verify(conn, cancel_requested)
            if registered_count != snapshot.row_count:
                raise ApplicationError("The registered external snapshot row count does not match", non_retryable=True)
            refreshed_source = get_external_delta_table(inputs.team_id, inputs.table_id)
            if refreshed_source.fingerprint != candidate.fingerprint:
                raise ApplicationError(
                    "The external table configuration changed during registration", non_retryable=True
                )
            registration.check_cancellation(cancel_requested)
            # Serialize opt-out with publication so a refresh already in flight cannot publish after it completes.
            with transaction.atomic():
                current_enrollment = (
                    ManagedWarehouseExternalTable.objects.for_team(inputs.team_id)
                    .select_for_update()
                    .get(id=enrolled.id)
                )
                if not current_enrollment.enabled:
                    return False
                published = publish_external_snapshot(conn, registration, candidate, cancel_requested)
    _record_published_snapshot(inputs.team_id, inputs.table_id, published)
    return published.version == candidate.version


@activity.defn
def register_external_table_activity(inputs: ExternalTableRegistrationAttempt) -> bool:
    if not settings.TEST:
        close_old_connections()
    logger = LOGGER.bind(team_id=inputs.team_id, table_id=str(inputs.table_id))
    try:
        with HeartbeaterSync(details=("external-table-registration", str(inputs.table_id)), logger=logger):
            applied = _register_external_table(inputs)
            logger.info("external_delta_registration_finished", applied=applied, attempt_token=inputs.attempt_token)
            return applied
    except Exception as error:
        ManagedWarehouseExternalTable.objects.for_team(inputs.team_id).filter(table_id=inputs.table_id).update(
            latest_error=type(error).__name__
        )
        logger.warning(
            "external_delta_registration_failed", error_type=type(error).__name__, attempt_token=inputs.attempt_token
        )
        raise ApplicationError(
            f"External Delta registration failed ({type(error).__name__})",
            non_retryable=isinstance(error, (ApplicationError, ValueError)),
        ) from None


@activity.defn
def external_table_sync_gate_activity(inputs: ExternalTableRegistrationInputs) -> bool:
    if not settings.TEST:
        close_old_connections()
    return ManagedWarehouseExternalTable.objects.for_team(inputs.team_id).filter(
        table_id=inputs.table_id, enabled=True
    ).exists() and external_table_sync_feature_enabled(inputs.team_id)


@activity.defn
def external_table_cleanup_inputs_activity(inputs: ExternalTableRegistrationAttempt) -> DuckLakeRegisterCleanupInputs:
    enrolled = ManagedWarehouseExternalTable.objects.for_team(inputs.team_id).get(table_id=inputs.table_id)
    names = registration_table_names_from_token(inputs.attempt_token)
    return DuckLakeRegisterCleanupInputs(
        team_id=inputs.team_id,
        schema_name=enrolled.warehouse_schema,
        table_names=[names.shadow_name, names.previous_name],
    )


@workflow.defn(name="ducklake-register.external-table")
class RegisterExternalTableWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> ExternalTableRegistrationInputs:
        loaded = json.loads(inputs[0])
        return ExternalTableRegistrationInputs(team_id=loaded["team_id"], table_id=uuid.UUID(loaded["table_id"]))

    @workflow.run
    async def run(self, inputs: ExternalTableRegistrationInputs) -> bool:
        should_register = await workflow.execute_activity(
            ducklake_register_data_imports_gate_activity,
            DuckLakeRegisterDataImportsGateInputs(team_id=inputs.team_id),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        if not should_register:
            return False
        if not await workflow.execute_activity(
            external_table_sync_gate_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        ):
            return False
        attempt = ExternalTableRegistrationAttempt(
            team_id=inputs.team_id, table_id=inputs.table_id, attempt_token=workflow.uuid4().hex
        )
        cleanup_inputs = await workflow.execute_activity(
            external_table_cleanup_inputs_activity,
            attempt,
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        try:
            return await workflow.execute_activity(
                register_external_table_activity,
                attempt,
                start_to_close_timeout=dt.timedelta(hours=4),
                heartbeat_timeout=dt.timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        finally:
            await workflow.execute_activity(
                cleanup_ducklake_registration_tables_activity,
                cleanup_inputs,
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=RetryPolicy(
                    maximum_attempts=10,
                    initial_interval=dt.timedelta(seconds=5),
                    maximum_interval=dt.timedelta(minutes=5),
                ),
            )
