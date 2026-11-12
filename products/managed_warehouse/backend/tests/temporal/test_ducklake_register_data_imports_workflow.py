import re
import json
import time
import uuid
import decimal
import datetime as dt
import contextlib
import dataclasses
from collections.abc import Callable, Iterator, Sequence
from functools import partial
from pathlib import Path
from typing import Any, cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings

import s3fs
import pyarrow as pa
import pyarrow.parquet as pq
from parameterized import parameterized
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.workflow import ParentClosePolicy
from trino.exceptions import TrinoUserError

from posthog.sync import database_sync_to_async

from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseSourceJobStatus
from products.managed_warehouse.backend.models import ManagedWarehouseSourceJob, ManagedWarehouseSourceLifecycle
from products.managed_warehouse.backend.temporal import (
    ducklake_register_data_imports_trino as trino_module,
    ducklake_register_data_imports_workflow as registration_module,
    ducklake_register_trino_landing as landing_module,
)
from products.managed_warehouse.backend.temporal.ducklake_register_data_imports_workflow import (
    ENGINE_DUCKGRES,
    ENGINE_TRINO,
    S3_COPY_BATCH_SIZE,
    DuckLakeRegisterDataImportsActivityInputs,
    DuckLakeRegisterDataImportsGateInputs,
    DuckLakeRegisterDataImportsInputs,
    DuckLakeRegisterDataImportsMetadata,
    DuckLakeRegisterDataImportsWorkflow,
    DuckLakeTrinoLandingSweepInputs,
    DuckLakeTrinoLandingSweepWorkflow,
    build_register_data_imports_workflow_id,
    copy_and_register_ducklake_data_imports_activity,
    ducklake_register_data_imports_gate_activity,
    prepare_ducklake_data_imports_registration_activity,
)
from products.managed_warehouse.backend.trino_compiler import TrinoTargetReadiness
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)


@pytest.fixture(autouse=True)
def _cp_no_rows():
    with (
        patch(
            "products.managed_warehouse.backend.facade.team_state.data_imports_schema",
            side_effect=lambda team_id: f"posthog_data_imports_team_{team_id}",
        ),
        patch(
            "products.managed_warehouse.backend.facade.team_state.data_imports_table_naming_version",
            return_value="copy_v1",
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _trino_engine_off(monkeypatch):
    monkeypatch.setattr(registration_module, "data_imports_through_trino", lambda organization_id: False)
    monkeypatch.setattr(registration_module, "data_imports_trino_flag", lambda organization_id: False)


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "enabled_flags, failing_flags, expected, internal_only, active",
    [
        ({"data-warehouse-scene"}, set(), True, False, True),
        ({"managed-warehouse-trino-query"}, set(), True, False, True),
        (set(), set(), False, False, True),
        (set(), set(), True, True, True),
        ({"managed-warehouse-trino-query"}, set(), False, True, False),
        ({"data-warehouse-scene"}, {"managed-warehouse-trino-query"}, True, False, True),
    ],
)
async def test_registration_gate_accepts_either_managed_warehouse_flag(
    monkeypatch, ateam, enabled_flags, failing_flags, expected, internal_only, active
):
    if internal_only:
        await ManagedWarehouseSourceLifecycle.objects.acreate(
            organization_id=ateam.organization_id,
            internal_only=True,
            background_loading_enabled=True,
            desired_active=active,
        )
    calls: list[dict[str, object]] = []

    def fake_feature_enabled(key, distinct_id, **kwargs):
        calls.append({"key": key, "distinct_id": distinct_id, **kwargs})
        if key in failing_flags:
            raise RuntimeError("flag evaluation failed")
        return key in enabled_flags

    monkeypatch.setattr(registration_module, "feature_enabled_or_false", fake_feature_enabled)

    result = await ducklake_register_data_imports_gate_activity(DuckLakeRegisterDataImportsGateInputs(team_id=ateam.id))

    assert result is expected
    assert calls[0]["distinct_id"] == str(ateam.organization_id)
    assert calls[0]["groups"] == {"organization": str(ateam.organization_id)}
    assert calls[0]["group_properties"] == {"organization": {"id": str(ateam.organization_id)}}


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "server_provisioned, trino_flag, expected",
    [(True, False, True), (True, None, True), (False, False, False), (False, None, None)],
)
async def test_registration_gate_requires_provisioned_duckgres_server_and_retries_an_unanswered_flag(
    monkeypatch, ateam, server_provisioned, trino_flag, expected
):
    monkeypatch.setattr(registration_module, "feature_enabled_or_false", lambda *args, **kwargs: True)
    monkeypatch.setattr(registration_module, "data_imports_trino_flag", lambda organization_id: trino_flag)
    monkeypatch.setattr(registration_module, "is_dev_mode", lambda: False)
    monkeypatch.setattr(
        registration_module,
        "get_duckgres_server_by_team_org",
        lambda team_id: MagicMock() if server_provisioned else None,
    )

    gate = ducklake_register_data_imports_gate_activity(DuckLakeRegisterDataImportsGateInputs(team_id=ateam.id))

    if expected is None:
        with pytest.raises(ApplicationError, match="gave no answer") as error:
            await gate
        assert error.value.non_retryable is False
    else:
        assert await gate is expected


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_prepare_registration_pins_the_import_jobs_prepared_generation(ateam):
    credential = await database_sync_to_async(DataWarehouseCredential.objects.create)(
        team=ateam,
        access_key="test_key",
        access_secret="test_secret",
    )
    source = await database_sync_to_async(ExternalDataSource.objects.create)(
        team=ateam,
        source_id="source",
        connection_id="connection",
        source_type="Postgres",
        status="Running",
    )
    prepared_queryable_folder = "customers__query_1234567890_abcdef12"
    table = await database_sync_to_async(DataWarehouseTable.objects.create)(
        team=ateam,
        name="customers",
        format="Delta",
        url_pattern="s3://bucket/path",
        credential=credential,
        external_data_source=source,
        columns={"id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"}},
        queryable_folder=prepared_queryable_folder,
    )
    schema = await database_sync_to_async(ExternalDataSchema.objects.create)(
        team=ateam,
        name="customers",
        source=source,
        table=table,
    )

    metadata = await prepare_ducklake_data_imports_registration_activity(
        DuckLakeRegisterDataImportsInputs(
            team_id=ateam.id,
            job_id="job-123",
            schema_id=schema.id,
            prepared_queryable_folder=prepared_queryable_folder,
        )
    )

    assert metadata is not None
    folder_path = await database_sync_to_async(schema.folder_path)()
    assert metadata.prepared_source_uri.endswith(f"/{folder_path}/{prepared_queryable_folder}")
    assert metadata.landing_uri == (
        f"s3://ducklake-dev/posthog_data_imports_team_{ateam.id}/postgres_customers/"
        f"_imports/{schema.id}/job-123/1234567890_abcdef12"
    )
    assert metadata.ducklake_schema_name == f"posthog_data_imports_team_{ateam.id}"
    assert metadata.ducklake_table_name == "postgres_customers"


@parameterized.expand(
    [
        (
            "job_scoped",
            "s3://ducklake/posthog_data_imports_team_1/postgres_customers/_imports/schema/job",
        ),
        (
            "generation_scoped",
            "s3://ducklake/posthog_data_imports_team_1/postgres_customers/_imports/schema/job/1234567890_abcdef12",
        ),
    ]
)
def test_landing_uri_normalizes_to_prepared_generation(_name: str, landing_uri: str) -> None:
    assert registration_module._generation_scoped_landing_uri(
        landing_uri,
        job_id="job",
        prepared_queryable_folder="customers__query_1234567890_abcdef12",
    ) == ("s3://ducklake/posthog_data_imports_team_1/postgres_customers/_imports/schema/job/1234567890_abcdef12")


def test_copy_activity_uses_s3_copy_and_local_duckgres_postgres_connection(monkeypatch):
    class FakeS3:
        def __init__(self) -> None:
            self.copy_calls: list[tuple[list[str], list[str], int]] = []

        def invalidate_cache(self, path: str | None = None) -> None:
            pass

        def find(self, prefix: str, detail: bool = False):
            files = {
                f"{prefix}/_ph_partition_key=2026-07/a.parquet": {"Size": 100, "type": "file"},
                f"{prefix}/_ph_partition_key=2026-08/b.parquet": {"Size": 200, "type": "file"},
            }
            return files if detail else list(files)

        def copy(self, sources: list[str], destinations: list[str], *, batch_size: int) -> None:
            self.copy_calls.append((sources, destinations, batch_size))

    s3 = FakeS3()
    monkeypatch.setattr(registration_module, "get_s3_client", lambda: s3)
    monkeypatch.setattr(registration_module, "_prepared_generation_is_current", lambda inputs: True)
    monkeypatch.setattr(registration_module, "is_dev_mode", lambda: True)
    monkeypatch.setattr(
        registration_module, "make_duckgres_conninfo", lambda team_id, **kwargs: "postgresql://duckgres"
    )

    conn = MagicMock()
    conn.closed = False
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    active_transaction: object | None = None
    transaction_tokens: list[object] = []
    executed_with_transactions: list[tuple[str, object | None]] = []

    @contextlib.contextmanager
    def transaction() -> Iterator[None]:
        nonlocal active_transaction
        transaction_token = object()
        transaction_tokens.append(transaction_token)
        active_transaction = transaction_token
        try:
            yield
        finally:
            active_transaction = None

    conn.transaction.side_effect = transaction

    def execute(query: object) -> MagicMock:
        query_text = str(query)
        executed_with_transactions.append((query_text, active_transaction))
        if "SELECT count(*) FROM read_parquet" in query_text:
            return MagicMock(fetchone=MagicMock(return_value=(2,)))
        if "SELECT count(*) FROM" in query_text:
            return MagicMock(fetchone=MagicMock(return_value=(2,)))
        return MagicMock()

    conn.execute.side_effect = execute
    connect = MagicMock(return_value=conn)
    monkeypatch.setattr(registration_module.psycopg, "connect", connect)
    monkeypatch.setattr(registration_module, "setup_duckgres_session", MagicMock())
    cancel_timer = MagicMock()
    cancel_timer_factory = MagicMock(return_value=cancel_timer)
    monkeypatch.setattr(registration_module, "_duckgres_cancel_delay", MagicMock(return_value=60.0))
    monkeypatch.setattr(registration_module.threading, "Timer", cancel_timer_factory)
    heartbeat_state = {"active": False}
    heartbeater = MagicMock()
    heartbeater.__enter__ = MagicMock(side_effect=lambda: heartbeat_state.update(active=True))
    heartbeater.__exit__ = MagicMock(side_effect=lambda *args: heartbeat_state.update(active=False))
    monkeypatch.setattr(registration_module, "HeartbeaterSync", MagicMock(return_value=heartbeater))
    workload_metrics = _mock_activity_workload_metrics(monkeypatch)

    def assert_heartbeat_active(_value: float) -> None:
        assert heartbeat_state["active"] is True

    workload_metrics.files.record.side_effect = assert_heartbeat_active
    workload_metrics.rows.record.side_effect = assert_heartbeat_active
    workload_metrics.bytes.record.side_effect = assert_heartbeat_active

    inputs = _activity_inputs()
    applied = copy_and_register_ducklake_data_imports_activity(inputs)

    assert applied is True
    connect.assert_called_once_with(
        "postgresql://duckgres",
        autocommit=True,
        options="-c duckgres.worker_cpu=4 -c duckgres.worker_memory=32Gi",
    )
    assert s3.copy_calls == [
        (
            [
                "source/team/customers__query_1234567890_abcdef12/_ph_partition_key=2026-07/a.parquet",
                "source/team/customers__query_1234567890_abcdef12/_ph_partition_key=2026-08/b.parquet",
            ],
            [
                "ducklake/posthog_data_imports_team_1/postgres_customers/_imports/schema/job/"
                "1234567890_abcdef12/_ph_partition_key=2026-07/a.parquet",
                "ducklake/posthog_data_imports_team_1/postgres_customers/_imports/schema/job/"
                "1234567890_abcdef12/_ph_partition_key=2026-08/b.parquet",
            ],
            S3_COPY_BATCH_SIZE,
        )
    ]
    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    registration_indexes = [index for index, query in enumerate(executed) if "ducklake_add_data_files" in query]
    verification_indexes = [index for index, query in enumerate(executed) if "SELECT count(*) FROM" in query]
    rename_indexes = [index for index, query in enumerate(executed) if "RENAME TO" in query]
    previous_cleanup_index = next(
        index for index, query in enumerate(executed) if "DROP TABLE IF EXISTS" in query and "__ph_previous_" in query
    )
    assert len(registration_indexes) == 1
    registration_query = executed[registration_indexes[0]]
    first_path = (
        "s3://ducklake/posthog_data_imports_team_1/postgres_customers/_imports/schema/job/"
        "1234567890_abcdef12/_ph_partition_key=2026-07/a.parquet"
    )
    second_path = (
        "s3://ducklake/posthog_data_imports_team_1/postgres_customers/_imports/schema/job/"
        "1234567890_abcdef12/_ph_partition_key=2026-08/b.parquet"
    )
    parquet_glob = (
        "s3://ducklake/posthog_data_imports_team_1/postgres_customers/_imports/schema/job/"
        "1234567890_abcdef12/**/*.[pP][aA][rR][qQ][uU][eE][tT]"
    )
    assert first_path in registration_query
    assert second_path in registration_query
    assert parquet_glob not in registration_query
    assert sum(parquet_glob in query for query in executed) == 2
    assert len(verification_indexes) == 2
    assert len(rename_indexes) == 2
    assert max(registration_indexes) < min(verification_indexes)
    assert max(verification_indexes) < min(rename_indexes)
    assert max(rename_indexes) < previous_cleanup_index
    assert "ALTER TABLE IF EXISTS" in executed[rename_indexes[0]]
    assert "postgres_customers" in executed[rename_indexes[0]]
    assert "__ph_previous_" in executed[rename_indexes[0]]
    assert executed[rename_indexes[0]].index("postgres_customers") < executed[rename_indexes[0]].index("__ph_previous_")
    assert "__ph_register_" in executed[rename_indexes[1]]
    assert "postgres_customers" in executed[rename_indexes[1]]
    assert executed[rename_indexes[1]].index("__ph_register_") < executed[rename_indexes[1]].index("postgres_customers")
    assert len(transaction_tokens) == 1
    assert [query for query, token in executed_with_transactions if token is transaction_tokens[0]] == [
        executed[index] for index in rename_indexes
    ]
    conn.transaction.assert_called_once_with()
    assert cancel_timer_factory.call_count == 1
    assert cancel_timer_factory.call_args.args[0] == 60.0
    assert callable(cancel_timer_factory.call_args.args[1])
    cancel_timer.start.assert_called_once_with()
    cancel_timer.cancel.assert_called_once_with()
    cancel_timer.join.assert_called_once_with(timeout=registration_module._DUCKGRES_CANCEL_TIMEOUT_SECONDS + 1)
    cancel_timer_factory.call_args.args[1]()
    conn.cancel_safe.assert_not_called()
    assert any("SET PARTITIONED BY" in query for query in executed)
    workload_metrics.files_getter.assert_called_once_with(team_id=1, schema_id="schema")
    workload_metrics.rows_getter.assert_called_once_with(team_id=1, schema_id="schema")
    workload_metrics.bytes_getter.assert_called_once_with(team_id=1, schema_id="schema")
    workload_metrics.files.record.assert_called_once_with(2.0)
    workload_metrics.rows.record.assert_called_once_with(2.0)
    workload_metrics.bytes.record.assert_called_once_with(300.0)


def test_copy_prepared_files_sees_a_rotating_folder_rewritten_after_an_earlier_copy(monkeypatch) -> None:
    def local_s3() -> s3fs.S3FileSystem:
        return s3fs.S3FileSystem(
            key=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            secret=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
            skip_instance_cache=True,
        )

    worker_s3 = local_s3()
    monkeypatch.setattr(registration_module, "get_s3_client", lambda: worker_s3)
    bucket = settings.OBJECT_STORAGE_BUCKET
    prefix = f"{bucket}/test_copy_rotating_folder_{uuid.uuid4().hex}"
    source_folder = f"{prefix}/source/table__query_a"
    partition_folder = f"{source_folder}/_ph_partition_key=2026-07"
    writer_s3 = local_s3()
    try:
        writer_s3.pipe(f"{partition_folder}/old.parquet", b"old")
        registration_module._copy_prepared_parquet_files(f"s3://{source_folder}", f"s3://{prefix}/first")

        writer_s3.rm(f"{partition_folder}/old.parquet")
        writer_s3.pipe(f"{partition_folder}/new.parquet", b"new")
        landing_paths, copied_bytes = registration_module._copy_prepared_parquet_files(
            f"s3://{source_folder}", f"s3://{prefix}/second"
        )

        expected = f"s3://{prefix}/second/_ph_partition_key=2026-07/new.parquet"
        assert landing_paths == [expected]
        assert copied_bytes == 3
        assert writer_s3.cat(expected.removeprefix("s3://")) == b"new"
        assert not writer_s3.exists(f"{prefix}/second/_ph_partition_key=2026-07/old.parquet")
    finally:
        writer_s3.rm(prefix, recursive=True)


def test_production_register_connection_requests_right_sized_duckgres_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = MagicMock()
    server.host = "duckgres.example.com"
    server.port = 5432
    server.database = "ducklake"
    server.username = "posthog"
    server.password = "example-password"
    monkeypatch.setattr(registration_module, "is_dev_mode", lambda: False)
    monkeypatch.setattr(registration_module, "_get_org_id_for_team", lambda _team_id: "org-id")
    monkeypatch.setattr(registration_module, "get_duckgres_server_for_organization", lambda _org_id: server)

    conn = MagicMock()
    connect = MagicMock()
    connect.return_value.__enter__.return_value = conn
    connect.return_value.__exit__.return_value = False
    monkeypatch.setattr(registration_module.psycopg, "connect", connect)

    with registration_module._connect_to_duckgres_for_team(1) as connected:
        assert connected is conn

    connect.assert_called_once_with(
        host="duckgres.example.com",
        port=5432,
        dbname="ducklake",
        user="posthog",
        password="example-password",
        autocommit=True,
        application_name="ducklake-register",
        options="-c duckgres.worker_cpu=4 -c duckgres.worker_memory=32Gi",
    )


def test_duckgres_cancel_watchdog_cancels_the_active_query(monkeypatch):
    conn = MagicMock()
    cancel_timer = MagicMock()
    cancel_timer_factory = MagicMock(return_value=cancel_timer)
    monkeypatch.setattr(registration_module.threading, "Timer", cancel_timer_factory)
    monkeypatch.setattr(registration_module, "_DUCKGRES_CANCEL_RETRY_SECONDS", 0.01)
    first_cancel_finished = registration_module.threading.Event()
    conn.cancel_safe.side_effect = lambda **_: first_cancel_finished.set()

    with registration_module._cancel_duckgres_query_after(conn, 30.0) as cancel_requested:
        callback_thread = registration_module.threading.Thread(target=cancel_timer_factory.call_args.args[1])
        callback_thread.start()
        assert first_cancel_finished.wait(timeout=1)

    callback_thread.join(timeout=1)
    assert not callback_thread.is_alive()
    assert cancel_requested.is_set()
    conn.cancel_safe.assert_called_with(timeout=registration_module._DUCKGRES_CANCEL_TIMEOUT_SECONDS)
    cancel_timer.cancel.assert_called_once_with()
    cancel_timer.join.assert_called_once_with(timeout=registration_module._DUCKGRES_CANCEL_TIMEOUT_SECONDS + 1)


def test_duckgres_cancel_watchdog_retries_after_an_idle_cancel(monkeypatch):
    conn = MagicMock()
    cancel_timer = MagicMock()
    cancel_timer_factory = MagicMock(return_value=cancel_timer)
    monkeypatch.setattr(registration_module.threading, "Timer", cancel_timer_factory)
    monkeypatch.setattr(registration_module, "_DUCKGRES_CANCEL_RETRY_SECONDS", 0.01)
    first_cancel_finished = registration_module.threading.Event()
    query_started = registration_module.threading.Event()
    query_canceled = registration_module.threading.Event()

    def cancel_safe(*, timeout: float) -> None:
        assert timeout == registration_module._DUCKGRES_CANCEL_TIMEOUT_SECONDS
        if first_cancel_finished.is_set() and query_started.is_set():
            query_canceled.set()
        first_cancel_finished.set()

    conn.cancel_safe.side_effect = cancel_safe

    with registration_module._cancel_duckgres_query_after(conn, 30.0):
        callback_thread = registration_module.threading.Thread(target=cancel_timer_factory.call_args.args[1])
        callback_thread.start()
        assert first_cancel_finished.wait(timeout=1)
        query_started.set()
        assert query_canceled.wait(timeout=1)

    callback_thread.join(timeout=1)
    assert not callback_thread.is_alive()
    assert conn.cancel_safe.call_count >= 2


def test_duckgres_cancel_watchdog_bounds_cancel_retries(monkeypatch):
    conn = MagicMock()
    cancel_timer = MagicMock()
    cancel_timer_factory = MagicMock(return_value=cancel_timer)
    monkeypatch.setattr(registration_module.threading, "Timer", cancel_timer_factory)
    monkeypatch.setattr(registration_module, "_DUCKGRES_CANCEL_RETRY_SECONDS", 0.0)
    retries_finished = registration_module.threading.Event()

    def cancel_safe(*, timeout: float) -> None:
        assert timeout == registration_module._DUCKGRES_CANCEL_TIMEOUT_SECONDS
        if conn.cancel_safe.call_count == registration_module._DUCKGRES_CANCEL_MAX_ATTEMPTS:
            retries_finished.set()

    conn.cancel_safe.side_effect = cancel_safe

    with registration_module._cancel_duckgres_query_after(conn, 30.0):
        callback_thread = registration_module.threading.Thread(target=cancel_timer_factory.call_args.args[1])
        callback_thread.start()
        assert retries_finished.wait(timeout=1)
        callback_thread.join(timeout=1)
        assert not callback_thread.is_alive()

    assert conn.cancel_safe.call_count == registration_module._DUCKGRES_CANCEL_MAX_ATTEMPTS


def test_duckgres_cancel_delay_includes_time_spent_copying(monkeypatch):
    activity_info = MagicMock(start_to_close_timeout=dt.timedelta(minutes=30))
    monkeypatch.setattr(registration_module.activity, "info", MagicMock(return_value=activity_info))
    monkeypatch.setattr(registration_module.time, "monotonic", MagicMock(return_value=400.0))

    assert registration_module._duckgres_cancel_delay(100.0) == 24 * 60


def test_duckgres_cancel_watchdog_rejects_an_exhausted_activity_budget(monkeypatch):
    timer_factory = MagicMock()
    monkeypatch.setattr(registration_module.threading, "Timer", timer_factory)

    with pytest.raises(TimeoutError, match="too close"):
        with registration_module._cancel_duckgres_query_after(MagicMock(), 0.0):
            pass

    timer_factory.assert_not_called()


def test_registration_stops_after_glob_query_cancellation(monkeypatch):
    monkeypatch.setattr(registration_module, "setup_duckgres_session", MagicMock())
    conn = MagicMock()
    conn.closed = False
    cancel_requested = registration_module.threading.Event()

    def execute(query: object) -> MagicMock:
        if "ducklake_add_data_files" in str(query):
            cancel_requested.set()
        return MagicMock()

    conn.execute.side_effect = execute
    landing_uri = registration_module._generation_scoped_landing_uri(
        _activity_inputs().metadata.landing_uri,
        job_id=_activity_inputs().job_id,
        prepared_queryable_folder=_activity_inputs().metadata.prepared_queryable_folder,
    )

    landing_paths = [f"{landing_uri}/{name}.parquet" for name in ("first", "second")]

    with pytest.raises(TimeoutError, match="activity deadline"):
        registration_module._register_prepared_parquet_files(
            _activity_inputs(),
            conn,
            landing_paths,
            cancel_requested=cancel_requested,
        )

    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    registration_queries = [query for query in executed if "ducklake_add_data_files" in query]
    assert len(registration_queries) == 1
    assert landing_paths[0] in registration_queries[0]
    assert f"{landing_uri}/{registration_module._PARQUET_FILE_GLOB}" not in registration_queries[0]
    assert not any("SELECT count(*)" in query for query in executed)
    assert sum("DROP TABLE" in query and "__ph_register_" in query for query in executed) == 1
    assert not any("RENAME TO" in query for query in executed)


def test_registration_splits_add_data_files_across_path_batches(monkeypatch):
    monkeypatch.setattr(registration_module, "setup_duckgres_session", MagicMock())
    monkeypatch.setattr(registration_module, "_ADD_DATA_FILES_BATCH_SIZE", 1)
    monkeypatch.setattr(registration_module, "_should_publish_prepared_generation", lambda inputs: True)
    conn = MagicMock()

    def execute(query: object) -> MagicMock:
        result = MagicMock()
        result.fetchone.return_value = (2,)
        return result

    conn.execute.side_effect = execute
    landing_uri = registration_module._generation_scoped_landing_uri(
        _activity_inputs().metadata.landing_uri,
        job_id=_activity_inputs().job_id,
        prepared_queryable_folder=_activity_inputs().metadata.prepared_queryable_folder,
    )
    landing_paths = [f"{landing_uri}/{name}.parquet" for name in ("first", "second")]

    registration_module._register_prepared_parquet_files(_activity_inputs(), conn, landing_paths)

    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    registration_queries = [query for query in executed if "ducklake_add_data_files" in query]
    parquet_glob = f"{landing_uri}/{registration_module._PARQUET_FILE_GLOB}"
    assert len(registration_queries) == 2
    assert landing_paths[0] in registration_queries[0]
    assert landing_paths[1] not in registration_queries[0]
    assert landing_paths[1] in registration_queries[1]
    assert landing_paths[0] not in registration_queries[1]
    assert not any(parquet_glob in query for query in registration_queries)
    assert sum(parquet_glob in query for query in executed) == 2


@pytest.mark.parametrize(
    ("is_current", "newer_completed", "expected"),
    [
        (True, None, True),
        (False, False, True),
        (False, True, False),
        (False, None, False),
    ],
)
def test_should_publish_prepared_generation(
    is_current: bool,
    newer_completed: bool | None,
    expected: bool,
    monkeypatch,
) -> None:
    monkeypatch.setattr(registration_module, "_prepared_generation_is_current", lambda inputs: is_current)
    monkeypatch.setattr(
        registration_module,
        "_current_prepared_queryable_folder",
        lambda inputs: None if newer_completed is None and not is_current else "customers__query_9999999999_ffffffff",
    )
    monkeypatch.setattr(
        registration_module,
        "_register_completed_for_generation",
        lambda **kwargs: bool(newer_completed),
    )

    assert registration_module._should_publish_prepared_generation(_activity_inputs()) is expected


@pytest.mark.parametrize(
    ("prepared_queryable_folder", "distinct_per_job"),
    [
        # A timestamped folder is one generation by construction, so its token stays the timestamp.
        ("customers__query_1234567890_abcdef12", False),
        # A rotation slot is reused by later syncs; the job tells the generations apart.
        ("customers__query_a", True),
    ],
)
def test_generation_token_tells_syncs_on_a_reused_folder_name_apart(
    prepared_queryable_folder: str, distinct_per_job: bool
) -> None:
    first = registration_module._generation_token(prepared_queryable_folder, "job-1")
    second = registration_module._generation_token(prepared_queryable_folder, "job-2")

    assert (first != second) is distinct_per_job
    if not distinct_per_job:
        assert first == "1234567890_abcdef12"


@pytest.mark.django_db
def test_stale_generation_still_publishes_when_the_current_slot_was_registered_by_an_earlier_job(team) -> None:
    # Slot names repeat: the generation now on slot a was published by job-3, and an earlier
    # generation on the same slot (job-1) was registered before. Job-2's generation on slot b is
    # stale but newer than anything DuckLake holds, so it must publish; treating job-1's registration
    # as "the newer folder already landed" left DuckLake a generation behind.
    source = ExternalDataSource.objects.create(
        team=team, source_id="source", connection_id="connection", source_type="Postgres", status="Running"
    )
    table = DataWarehouseTable.objects.create(
        team=team,
        name="customers",
        format="Delta",
        url_pattern="s3://bucket/path",
        external_data_source=source,
        queryable_folder="customers__query_a",
    )
    schema = ExternalDataSchema.objects.create(
        team=team,
        name="customers",
        source=source,
        table=table,
        sync_type_config={
            "query_folder_state": {
                "customers__query": {
                    "active": "customers__query_a",
                    "active_since": "2026-08-19T10:00:00+00:00",
                    "active_job_id": "job-3",
                    "history_since": "2026-08-19T08:00:00+00:00",
                    "inactive_since": {"customers__query_b": "2026-08-19T10:00:00+00:00"},
                }
            }
        },
    )
    started_at = dt.datetime(2026, 8, 19, 9, tzinfo=dt.UTC)
    earlier_registration = registration_module._register_source_job_update(
        inputs=DuckLakeRegisterDataImportsInputs(
            team_id=team.id, job_id="job-1", schema_id=schema.id, prepared_queryable_folder="customers__query_a"
        ),
        status=ManagedWarehouseSourceJobStatus.COMPLETED,
        started_at=started_at,
        finished_at=started_at,
    )
    ManagedWarehouseSourceJob.objects.for_team(team.id).create(
        team=team,
        environment_id=team.id,
        schema_id=schema.id,
        source_job_id="job-1",
        attempt_id=earlier_registration.attempt_id,
        workflow_type=ManagedWarehouseSourceJob.WorkflowType.REGISTER,
        status=ManagedWarehouseSourceJob.Status.COMPLETED,
        started_at=started_at,
        finished_at=started_at,
    )
    stale_inputs = DuckLakeRegisterDataImportsActivityInputs(
        team_id=team.id,
        job_id="job-2",
        metadata=DuckLakeRegisterDataImportsMetadata(
            source_schema_id=str(schema.id),
            prepared_queryable_folder="customers__query_b",
            prepared_source_uri="s3://source/team/customers__query_b",
            landing_uri="s3://ducklake/posthog_data_imports_team_1/postgres_customers/_imports/schema/job-2",
            ducklake_schema_name="posthog_data_imports_team_1",
            ducklake_table_name="postgres_customers",
        ),
    )

    assert registration_module._should_publish_prepared_generation(stale_inputs) is True


def test_copy_activity_registers_when_prepared_generation_is_no_longer_current(monkeypatch):
    monkeypatch.setattr(
        registration_module,
        "_copy_prepared_parquet_files",
        lambda source_uri, landing_uri: ([f"{landing_uri}/file.parquet"], 100),
    )
    monkeypatch.setattr(registration_module, "_prepared_generation_is_current", lambda inputs: False)
    monkeypatch.setattr(registration_module, "_should_publish_prepared_generation", lambda inputs: True)
    conn = MagicMock()

    def execute(query: object) -> MagicMock:
        if "SELECT count(*) FROM" in str(query):
            return MagicMock(fetchone=MagicMock(return_value=(1,)))
        return MagicMock()

    conn.execute.side_effect = execute
    monkeypatch.setattr(
        registration_module,
        "_connect_to_duckgres_for_team",
        lambda team_id: contextlib.nullcontext(conn),
    )
    monkeypatch.setattr(registration_module, "setup_duckgres_session", MagicMock())
    heartbeater = MagicMock()
    heartbeater.__enter__ = MagicMock(return_value=heartbeater)
    heartbeater.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(registration_module, "HeartbeaterSync", MagicMock(return_value=heartbeater))
    workload_metrics = _mock_activity_workload_metrics(monkeypatch)

    assert copy_and_register_ducklake_data_imports_activity(_activity_inputs()) is True

    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert any("ducklake_add_data_files" in query for query in executed)
    assert sum("RENAME TO" in query for query in executed) == 2
    workload_metrics.files.record.assert_called_once_with(1.0)
    workload_metrics.rows.record.assert_called_once_with(1.0)
    workload_metrics.bytes.record.assert_called_once_with(100.0)


def test_copy_activity_does_not_publish_a_row_count_mismatch_when_cleanup_fails(monkeypatch):
    monkeypatch.setattr(
        registration_module,
        "_copy_prepared_parquet_files",
        lambda source_uri, landing_uri: ([f"{landing_uri}/file.parquet"], 100),
    )
    monkeypatch.setattr(registration_module, "_prepared_generation_is_current", lambda inputs: True)
    conn = MagicMock()
    conn.closed = False
    counts = iter([(10,), (9,)])

    def execute(query: object) -> MagicMock:
        query_text = str(query)
        if "SELECT count(*) FROM" in query_text:
            return MagicMock(fetchone=MagicMock(return_value=next(counts)))
        if "DROP TABLE IF EXISTS" in query_text and "__ph_register_" in query_text:
            raise RuntimeError("cleanup failed")
        return MagicMock()

    conn.execute.side_effect = execute
    monkeypatch.setattr(
        registration_module,
        "_connect_to_duckgres_for_team",
        lambda team_id: contextlib.nullcontext(conn),
    )
    monkeypatch.setattr(registration_module, "setup_duckgres_session", MagicMock())
    monkeypatch.setattr(registration_module.time, "sleep", lambda _seconds: None)
    heartbeater = MagicMock()
    heartbeater.__enter__ = MagicMock(return_value=heartbeater)
    heartbeater.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(registration_module, "HeartbeaterSync", MagicMock(return_value=heartbeater))

    with pytest.raises(ApplicationError, match="row count mismatch"):
        copy_and_register_ducklake_data_imports_activity(_activity_inputs())

    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    conn.transaction.assert_not_called()
    assert (
        sum("DROP TABLE IF EXISTS" in query and "__ph_register_" in query for query in executed)
        == registration_module._CLEANUP_DROP_ATTEMPTS
    )
    assert not any("RENAME TO" in query for query in executed)


def test_copy_activity_skips_publish_when_newer_generation_already_landed(monkeypatch):
    monkeypatch.setattr(
        registration_module,
        "_copy_prepared_parquet_files",
        lambda source_uri, landing_uri: ([f"{landing_uri}/file.parquet"], 100),
    )
    monkeypatch.setattr(registration_module, "_should_publish_prepared_generation", lambda inputs: False)
    conn = MagicMock()
    conn.closed = False

    def execute(query: object) -> MagicMock:
        if "SELECT count(*) FROM" in str(query):
            return MagicMock(fetchone=MagicMock(return_value=(10,)))
        return MagicMock()

    conn.execute.side_effect = execute
    monkeypatch.setattr(
        registration_module,
        "_connect_to_duckgres_for_team",
        lambda team_id: contextlib.nullcontext(conn),
    )
    monkeypatch.setattr(registration_module, "setup_duckgres_session", MagicMock())
    heartbeater = MagicMock()
    heartbeater.__enter__ = MagicMock(return_value=heartbeater)
    heartbeater.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(registration_module, "HeartbeaterSync", MagicMock(return_value=heartbeater))
    stale_counter = MagicMock()
    stale_metric = MagicMock(return_value=stale_counter)
    monkeypatch.setattr(registration_module, "get_ducklake_register_data_imports_stale_metric", stale_metric)

    assert copy_and_register_ducklake_data_imports_activity(_activity_inputs()) is False

    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    conn.transaction.assert_not_called()
    assert any("ducklake_add_data_files" in query for query in executed)
    assert sum("DROP TABLE IF EXISTS" in query and "__ph_register_" in query for query in executed) == 1
    assert not any("RENAME TO" in query for query in executed)
    stale_metric.assert_called_once_with(team_id=1, schema_id="schema", stage="publish")
    stale_counter.add.assert_called_once_with(1)


def test_registration_tables_are_owned_by_one_activity_attempt(monkeypatch):
    attempt_ids = iter([uuid.UUID(int=1), uuid.UUID(int=2)])
    monkeypatch.setattr(registration_module.uuid, "uuid4", lambda: next(attempt_ids))

    first = registration_module._new_registration_table_names()
    second = registration_module._new_registration_table_names()

    assert {first.shadow_name, first.previous_name}.isdisjoint({second.shadow_name, second.previous_name})
    assert first.shadow_name == f"__ph_register_{uuid.UUID(int=1).hex}"
    assert first.previous_name == f"__ph_previous_{uuid.UUID(int=1).hex}"
    assert all(
        len(name) <= 63 for name in (first.shadow_name, first.previous_name, second.shadow_name, second.previous_name)
    )


def test_unknown_publish_commit_error_survives_temporary_table_cleanup(monkeypatch):
    monkeypatch.setattr(registration_module, "_prepared_generation_is_current", lambda inputs: True)
    monkeypatch.setattr(registration_module, "setup_duckgres_session", MagicMock())
    monkeypatch.setattr(registration_module.time, "sleep", lambda _seconds: None)
    conn = MagicMock()
    conn.closed = False
    commit_error = RuntimeError("commit acknowledgement lost")

    @contextlib.contextmanager
    def transaction() -> Iterator[None]:
        yield
        raise commit_error

    conn.transaction.side_effect = transaction

    def execute(query: object) -> MagicMock:
        query_text = str(query)
        if "SELECT count(*) FROM" in query_text:
            return MagicMock(fetchone=MagicMock(return_value=(10,)))
        if "DROP TABLE IF EXISTS" in query_text:
            raise RuntimeError("cleanup unavailable")
        return MagicMock()

    conn.execute.side_effect = execute

    with pytest.raises(RuntimeError) as error:
        registration_module._register_prepared_parquet_files(
            _activity_inputs(),
            conn,
            [f"{_activity_inputs().metadata.landing_uri}/file.parquet"],
        )

    assert error.value is commit_error
    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert len([query for query in executed if "RENAME TO" in query]) == 2
    assert (
        sum("DROP TABLE IF EXISTS" in query and "__ph_register_" in query for query in executed)
        == registration_module._CLEANUP_DROP_ATTEMPTS
    )
    assert (
        sum("DROP TABLE IF EXISTS" in query and "__ph_previous_" in query for query in executed)
        == registration_module._CLEANUP_DROP_ATTEMPTS
    )


def test_cleanup_skips_a_closed_connection_without_reporting(monkeypatch):
    sleep = MagicMock()
    capture = MagicMock()
    monkeypatch.setattr(registration_module.time, "sleep", sleep)
    monkeypatch.setattr(registration_module, "capture_exception", capture)
    conn = MagicMock()
    conn.closed = True

    registration_module._cleanup_registration_tables(conn, "schema", ["__ph_register_x"])

    conn.execute.assert_not_called()
    sleep.assert_not_called()
    capture.assert_not_called()


def test_cleanup_aborts_a_broken_connection_without_reporting(monkeypatch):
    sleep = MagicMock()
    capture = MagicMock()
    monkeypatch.setattr(registration_module.time, "sleep", sleep)
    monkeypatch.setattr(registration_module, "capture_exception", capture)
    conn = MagicMock()
    conn.closed = False
    conn.execute.side_effect = registration_module.psycopg.OperationalError(
        "SSL connection has been closed unexpectedly"
    )

    registration_module._cleanup_registration_tables(conn, "schema", ["__ph_register_x", "__ph_previous_x"])

    assert conn.execute.call_count == 1
    sleep.assert_not_called()
    capture.assert_not_called()


@pytest.mark.asyncio
async def test_workflow_does_not_record_duration_when_disabled(monkeypatch):
    execute_activity = AsyncMock(return_value=False)
    metrics = _mock_workflow_metrics(monkeypatch)
    monkeypatch.setattr(registration_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(registration_module.workflow, "now", MagicMock(return_value=dt.datetime(2026, 7, 30)))

    await DuckLakeRegisterDataImportsWorkflow().run(_workflow_inputs())

    metrics.started_getter.assert_not_called()
    metrics.duration_getter.assert_not_called()
    metrics.finished_getter.assert_not_called()
    metrics.last_success_getter.assert_not_called()


@pytest.mark.asyncio
async def test_workflow_records_end_to_end_duration_after_gate(monkeypatch):
    started_at = dt.datetime(2026, 7, 30, 12, 0, 0)
    finished_at = started_at + dt.timedelta(minutes=7, seconds=12)
    execute_activity = AsyncMock(side_effect=[True, None, _activity_inputs().metadata, True, None, None])
    metrics = _mock_workflow_metrics(monkeypatch)
    monkeypatch.setattr(registration_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(registration_module.workflow, "uuid4", MagicMock(return_value=uuid.UUID(int=7)))
    monkeypatch.setattr(
        registration_module.workflow,
        "now",
        MagicMock(side_effect=[started_at, finished_at, finished_at]),
    )

    await DuckLakeRegisterDataImportsWorkflow().run(_workflow_inputs())

    cleanup_call = next(
        call
        for call in execute_activity.await_args_list
        if call.args[0] is registration_module.cleanup_ducklake_registration_tables_activity
    )
    assert cleanup_call.args[1].table_names == [
        f"__ph_register_{uuid.UUID(int=7).hex}",
        f"__ph_previous_{uuid.UUID(int=7).hex}",
    ]
    metric_identifiers = {"team_id": 1, "schema_id": str(_workflow_inputs().schema_id)}
    metrics.started_getter.assert_called_once_with(**metric_identifiers)
    metrics.started.add.assert_called_once_with(1)
    metrics.finished_getter.assert_called_once_with(**metric_identifiers, status="completed")
    metrics.finished.add.assert_called_once_with(1)
    metrics.duration_getter.assert_called_once_with(**metric_identifiers, status="completed")
    metrics.duration.record.assert_called_once_with(432.0)
    metrics.last_success_getter.assert_called_once_with(**metric_identifiers)
    metrics.last_success.set.assert_called_once_with(finished_at.timestamp())
    registration_call = next(
        call
        for call in execute_activity.await_args_list
        if call.args[0] is copy_and_register_ducklake_data_imports_activity
    )
    assert registration_call.kwargs["start_to_close_timeout"] == dt.timedelta(hours=4)
    assert registration_call.kwargs["retry_policy"].maximum_attempts == 1
    assert _recorded_source_job_statuses(execute_activity) == [
        registration_module.ManagedWarehouseSourceJobStatus.RUNNING,
        registration_module.ManagedWarehouseSourceJobStatus.COMPLETED,
    ]


@pytest.mark.asyncio
async def test_workflow_skips_source_job_state_for_pre_patch_history(monkeypatch):
    started_at = dt.datetime(2026, 7, 30, 12, 0, 0)
    finished_at = started_at + dt.timedelta(minutes=7)
    execute_activity = AsyncMock(side_effect=[True, _activity_inputs().metadata, True])
    metrics = _mock_workflow_metrics(monkeypatch)
    patched = MagicMock(return_value=False)
    monkeypatch.setattr(registration_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(registration_module.workflow, "patched", patched)
    monkeypatch.setattr(
        registration_module.workflow,
        "now",
        MagicMock(side_effect=[started_at, finished_at]),
    )

    await DuckLakeRegisterDataImportsWorkflow().run(_workflow_inputs())

    patched.assert_any_call(registration_module._SOURCE_JOB_STATE_PATCH_ID)
    patched.assert_any_call(registration_module._CLEANUP_FINALIZER_PATCH_ID)
    assert _recorded_source_job_statuses(execute_activity) == []
    metrics.finished_getter.assert_called_once_with(
        team_id=1,
        schema_id=str(_workflow_inputs().schema_id),
        status="completed",
    )


@pytest.mark.asyncio
async def test_workflow_retries_completed_state_without_recording_failure(monkeypatch):
    started_at = dt.datetime(2026, 7, 30, 12, 0, 0)
    completed_at = started_at + dt.timedelta(minutes=6)
    finished_at = started_at + dt.timedelta(minutes=7)
    execute_activity = AsyncMock(
        side_effect=[
            True,
            None,
            _activity_inputs().metadata,
            True,
            None,
            RuntimeError("completion write failed"),
            None,
        ]
    )
    metrics = _mock_workflow_metrics(monkeypatch)
    monkeypatch.setattr(registration_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(registration_module.workflow, "uuid4", MagicMock(return_value=uuid.UUID(int=7)))
    monkeypatch.setattr(
        registration_module.workflow,
        "now",
        MagicMock(side_effect=[started_at, completed_at, finished_at]),
    )

    await DuckLakeRegisterDataImportsWorkflow().run(_workflow_inputs())

    assert _recorded_source_job_statuses(execute_activity) == [
        registration_module.ManagedWarehouseSourceJobStatus.RUNNING,
        registration_module.ManagedWarehouseSourceJobStatus.COMPLETED,
        registration_module.ManagedWarehouseSourceJobStatus.COMPLETED,
    ]
    metrics.finished_getter.assert_called_once_with(
        team_id=1,
        schema_id=str(_workflow_inputs().schema_id),
        status="completed",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "engine, sweep_patched, start_error, expect_child",
    [
        pytest.param(ENGINE_DUCKGRES, True, None, False, id="duckgres"),
        pytest.param(ENGINE_TRINO, True, None, True, id="trino"),
        pytest.param(ENGINE_TRINO, False, None, False, id="trino_before_the_sweep_patch"),
        pytest.param(ENGINE_TRINO, True, WorkflowAlreadyStartedError("id", "type"), True, id="trino_sweep_exists"),
    ],
)
async def test_workflow_cleanup_finalizer_runs_when_copy_activity_fails(
    monkeypatch, engine, sweep_patched, start_error, expect_child
):
    metadata = dataclasses.replace(_activity_inputs().metadata, engine=engine)
    if engine == ENGINE_TRINO:
        metadata = dataclasses.replace(
            metadata,
            landing_uri="s3://ducklake/_ph_imports/posthog_data_imports_team_1/postgres_customers/schema/job",
        )
    execute_activity = AsyncMock(
        side_effect=[
            True,
            None,
            metadata,
            RuntimeError("register worker died"),
            None,
            None,
        ]
    )
    start_child_workflow = AsyncMock(side_effect=start_error)
    _mock_workflow_metrics(monkeypatch)
    monkeypatch.setattr(
        registration_module.workflow,
        "patched",
        MagicMock(
            side_effect=lambda patch_id: sweep_patched or patch_id != registration_module._TRINO_LANDING_SWEEP_PATCH_ID
        ),
    )
    monkeypatch.setattr(registration_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(registration_module.workflow, "start_child_workflow", start_child_workflow)
    monkeypatch.setattr(registration_module.workflow, "uuid4", MagicMock(return_value=uuid.UUID(int=9)))
    monkeypatch.setattr(registration_module.workflow, "now", MagicMock(return_value=MINTED_AT))

    with pytest.raises(RuntimeError, match="register worker died"):
        await DuckLakeRegisterDataImportsWorkflow().run(_workflow_inputs())

    copy_call = next(
        call
        for call in execute_activity.await_args_list
        if call.args[0] is copy_and_register_ducklake_data_imports_activity
    )
    cleanup_call = next(
        call
        for call in execute_activity.await_args_list
        if call.args[0] is registration_module.cleanup_ducklake_registration_tables_activity
    )
    names = copy_call.args[1].registration_table_names
    assert names is not None
    assert cleanup_call.args[1].table_names == [names.shadow_name, names.previous_name]
    assert cleanup_call.args[1].schema_name == _activity_inputs().metadata.ducklake_schema_name
    if not expect_child:
        start_child_workflow.assert_not_awaited()
        return
    token = names.shadow_name.removeprefix("__ph_register_")
    start_child_workflow.assert_awaited_once_with(
        DuckLakeTrinoLandingSweepWorkflow.run,
        DuckLakeTrinoLandingSweepInputs(
            team_id=1,
            attempt_uri=(
                "s3://ducklake/_ph_imports/posthog_data_imports_team_1/postgres_customers/schema/job/"
                f"1234567890_abcdef12/{token}"
            ),
            delete_after=MINTED_AT
            + registration_module._SWEEP_MIN_AGE
            + registration_module._LANDING_SWEEP_CLOCK_MARGIN,
        ),
        id=f"ducklake-register-data-imports-landing-sweep-1-{_workflow_inputs().schema_id}-{token}",
        parent_close_policy=ParentClosePolicy.ABANDON,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("delay", [dt.timedelta(hours=2), dt.timedelta(hours=-1)], ids=["waits", "due"])
async def test_landing_sweep_workflow_waits_for_the_sweep_age_before_sweeping(monkeypatch, delay) -> None:
    inputs = DuckLakeTrinoLandingSweepInputs(
        team_id=1, attempt_uri="s3://b/_ph_imports/a", delete_after=MINTED_AT + delay
    )
    sleep = AsyncMock()
    execute_activity = AsyncMock()
    monkeypatch.setattr(registration_module.workflow, "now", MagicMock(return_value=MINTED_AT))
    monkeypatch.setattr(registration_module.workflow, "sleep", sleep)
    monkeypatch.setattr(registration_module.workflow, "execute_activity", execute_activity)

    await DuckLakeTrinoLandingSweepWorkflow().run(inputs)

    if delay > dt.timedelta(0):
        sleep.assert_awaited_once_with(delay)
    else:
        sleep.assert_not_awaited()
    assert [call.args for call in execute_activity.await_args_list] == [
        (registration_module.sweep_trino_registration_landing_activity, inputs)
    ]


def test_cleanup_activity_drops_requested_tables_and_sweeps_stale_ones(monkeypatch):
    stale_shadow = f"__ph_register_{uuid.UUID(int=3).hex}"
    conn = MagicMock()

    def execute(query: object) -> MagicMock:
        if "FROM __ducklake_metadata_ducklake.ducklake_table" in str(query):
            return MagicMock(fetchall=MagicMock(return_value=[(stale_shadow,)]))
        return MagicMock()

    conn.execute.side_effect = execute
    monkeypatch.setattr(
        registration_module,
        "_connect_to_duckgres_for_team",
        lambda team_id: contextlib.nullcontext(conn),
    )
    monkeypatch.setattr(registration_module, "setup_duckgres_session", MagicMock())

    registration_module.cleanup_ducklake_registration_tables_activity(
        registration_module.DuckLakeRegisterCleanupInputs(
            team_id=1,
            schema_name="posthog_data_imports_team_1",
            table_names=["__ph_register_abc", "__ph_previous_abc"],
        )
    )

    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert sum("DROP TABLE IF EXISTS" in query and "__ph_register_abc" in query for query in executed) == 1
    assert sum("DROP TABLE IF EXISTS" in query and "__ph_previous_abc" in query for query in executed) == 1
    assert sum("DROP TABLE IF EXISTS" in query and stale_shadow in query for query in executed) == 1
    sweep_query = next(query for query in executed if "FROM __ducklake_metadata_ducklake.ducklake_table" in query)
    assert registration_module._REGISTRATION_TABLE_REGEX in sweep_query
    assert "posthog_data_imports_team_1" in sweep_query
    assert "CAST" in sweep_query and "AS INTERVAL" in sweep_query


def test_cleanup_activity_survives_sweep_failure(monkeypatch):
    conn = MagicMock()

    def execute(query: object) -> MagicMock:
        if "FROM __ducklake_metadata_ducklake.ducklake_table" in str(query):
            raise RuntimeError("metadata catalog unavailable")
        return MagicMock()

    conn.execute.side_effect = execute
    monkeypatch.setattr(
        registration_module,
        "_connect_to_duckgres_for_team",
        lambda team_id: contextlib.nullcontext(conn),
    )
    monkeypatch.setattr(registration_module, "setup_duckgres_session", MagicMock())
    monkeypatch.setattr(registration_module, "capture_exception", MagicMock())

    registration_module.cleanup_ducklake_registration_tables_activity(
        registration_module.DuckLakeRegisterCleanupInputs(
            team_id=1,
            schema_name="posthog_data_imports_team_1",
            table_names=["__ph_register_abc", "__ph_previous_abc"],
        )
    )

    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert sum("DROP TABLE IF EXISTS" in query and "__ph_register_abc" in query for query in executed) == 1
    assert sum("DROP TABLE IF EXISTS" in query and "__ph_previous_abc" in query for query in executed) == 1


def test_sweep_query_executes_on_duckdb_and_applies_the_guards():
    import duckdb

    conn = duckdb.connect()
    conn.execute('CREATE SCHEMA "__ducklake_metadata_ducklake"')
    conn.execute(
        'CREATE TABLE "__ducklake_metadata_ducklake".ducklake_table '
        "(table_id BIGINT, schema_id BIGINT, table_name VARCHAR, begin_snapshot BIGINT, end_snapshot BIGINT)"
    )
    conn.execute(
        'CREATE TABLE "__ducklake_metadata_ducklake".ducklake_schema '
        "(schema_id BIGINT, schema_name VARCHAR, end_snapshot BIGINT)"
    )
    conn.execute(
        'CREATE TABLE "__ducklake_metadata_ducklake".ducklake_snapshot (snapshot_id BIGINT, snapshot_time VARCHAR)'
    )
    conn.execute(
        "INSERT INTO \"__ducklake_metadata_ducklake\".ducklake_schema VALUES (1, 'posthog_data_imports_team_1', NULL)"
    )
    old_shadow = f"__ph_register_{uuid.UUID(int=1).hex}"
    young_shadow = f"__ph_register_{uuid.UUID(int=2).hex}"
    expired_snapshot_shadow = f"__ph_previous_{uuid.UUID(int=3).hex}"
    conn.execute(
        'INSERT INTO "__ducklake_metadata_ducklake".ducklake_snapshot '
        "VALUES (10, CAST(now() - INTERVAL '2 days' AS VARCHAR)), (11, CAST(now() AS VARCHAR))"
    )
    conn.execute(
        'INSERT INTO "__ducklake_metadata_ducklake".ducklake_table VALUES '
        f"(100, 1, '{old_shadow}', 10, NULL), "
        f"(101, 1, '{young_shadow}', 11, NULL), "
        f"(102, 1, '{expired_snapshot_shadow}', 9, NULL), "  # snapshot row 9 does not exist
        f"(103, 1, 'stripe_prod_customer', 10, NULL), "  # non-matching name, old
        f"(104, 1, '{old_shadow}', 10, 11)"  # already dropped
    )

    rendered = registration_module._sweep_query("posthog_data_imports_team_1").as_string()
    swept = {row[0] for row in conn.execute(rendered).fetchall()}

    assert swept == {old_shadow, expired_snapshot_shadow}


def test_register_uses_workflow_minted_names(monkeypatch):
    monkeypatch.setattr(registration_module, "_should_publish_prepared_generation", lambda inputs: True)
    monkeypatch.setattr(registration_module, "setup_duckgres_session", MagicMock())
    conn = MagicMock()

    def execute(query: object) -> MagicMock:
        if "SELECT count(*) FROM" in str(query):
            return MagicMock(fetchone=MagicMock(return_value=(10,)))
        return MagicMock()

    conn.execute.side_effect = execute
    names = registration_module.registration_table_names_from_token("feedc0de" * 4)
    inputs = dataclasses.replace(_activity_inputs(), registration_table_names=names)

    registration_module._register_prepared_parquet_files(
        inputs,
        conn,
        [f"{inputs.metadata.landing_uri}/file.parquet"],
    )

    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert any("CREATE TABLE" in query and names.shadow_name in query for query in executed)
    assert any("RENAME TO" in query and names.previous_name in query for query in executed)


@pytest.mark.asyncio
async def test_workflow_records_end_to_end_duration_on_post_gate_failure(monkeypatch):
    started_at = dt.datetime(2026, 7, 30, 12, 0, 0)
    failed_at = started_at + dt.timedelta(seconds=5)
    execute_activity = AsyncMock(side_effect=[True, None, RuntimeError("prepare failed"), None])
    metrics = _mock_workflow_metrics(monkeypatch)
    monkeypatch.setattr(registration_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(
        registration_module.workflow,
        "now",
        MagicMock(side_effect=[started_at, failed_at, failed_at]),
    )

    with pytest.raises(RuntimeError, match="prepare failed"):
        await DuckLakeRegisterDataImportsWorkflow().run(_workflow_inputs())

    metric_identifiers = {"team_id": 1, "schema_id": str(_workflow_inputs().schema_id)}
    metrics.started_getter.assert_called_once_with(**metric_identifiers)
    metrics.started.add.assert_called_once_with(1)
    metrics.finished_getter.assert_called_once_with(**metric_identifiers, status="failed")
    metrics.finished.add.assert_called_once_with(1)
    metrics.duration_getter.assert_called_once_with(**metric_identifiers, status="failed")
    metrics.duration.record.assert_called_once_with(5.0)
    metrics.last_success_getter.assert_not_called()
    assert _recorded_source_job_statuses(execute_activity) == [
        registration_module.ManagedWarehouseSourceJobStatus.RUNNING,
        registration_module.ManagedWarehouseSourceJobStatus.FAILED,
    ]


@pytest.mark.asyncio
async def test_workflow_records_stale_prepared_generation(monkeypatch):
    started_at = dt.datetime(2026, 7, 30, 12, 0, 0)
    finished_at = started_at + dt.timedelta(seconds=2)
    execute_activity = AsyncMock(side_effect=[True, None, None, None])
    metrics = _mock_workflow_metrics(monkeypatch)
    monkeypatch.setattr(registration_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(
        registration_module.workflow,
        "now",
        MagicMock(side_effect=[started_at, finished_at, finished_at]),
    )

    await DuckLakeRegisterDataImportsWorkflow().run(_workflow_inputs())

    metric_identifiers = {"team_id": 1, "schema_id": str(_workflow_inputs().schema_id)}
    metrics.finished_getter.assert_called_once_with(**metric_identifiers, status="stale")
    metrics.duration.record.assert_called_once_with(2.0)
    metrics.last_success_getter.assert_not_called()
    assert _recorded_source_job_statuses(execute_activity) == [
        registration_module.ManagedWarehouseSourceJobStatus.RUNNING,
        registration_module.ManagedWarehouseSourceJobStatus.STALE,
    ]


def _mock_workflow_metrics(monkeypatch):
    metrics = MagicMock()
    monkeypatch.setattr(registration_module.workflow, "patched", MagicMock(return_value=True))
    metrics.duration_getter = MagicMock(return_value=metrics.duration)
    metrics.finished_getter = MagicMock(return_value=metrics.finished)
    metrics.started_getter = MagicMock(return_value=metrics.started)
    metrics.last_success_getter = MagicMock(return_value=metrics.last_success)
    monkeypatch.setattr(
        registration_module,
        "get_ducklake_register_data_imports_duration_metric",
        metrics.duration_getter,
    )
    monkeypatch.setattr(
        registration_module,
        "get_ducklake_register_data_imports_finished_metric",
        metrics.finished_getter,
    )
    monkeypatch.setattr(
        registration_module,
        "get_ducklake_register_data_imports_started_metric",
        metrics.started_getter,
    )
    monkeypatch.setattr(
        registration_module,
        "get_ducklake_register_data_imports_last_success_metric",
        metrics.last_success_getter,
    )
    return metrics


def _mock_activity_workload_metrics(monkeypatch):
    metrics = MagicMock()
    metrics.files_getter = MagicMock(return_value=metrics.files)
    metrics.rows_getter = MagicMock(return_value=metrics.rows)
    metrics.bytes_getter = MagicMock(return_value=metrics.bytes)
    monkeypatch.setattr(
        registration_module,
        "get_ducklake_register_data_imports_files_metric",
        metrics.files_getter,
    )
    monkeypatch.setattr(
        registration_module,
        "get_ducklake_register_data_imports_rows_metric",
        metrics.rows_getter,
    )
    monkeypatch.setattr(
        registration_module,
        "get_ducklake_register_data_imports_bytes_metric",
        metrics.bytes_getter,
    )
    return metrics


def test_register_worker_memory_stays_above_the_oom_floor() -> None:
    """Registration workers must keep enough memory to materialize a generation.

    The exact-string assertions elsewhere in this module pin whatever value is
    configured; they pass just as happily on a value too small to run. This
    pins the floor instead. Registration reads a whole generation through
    read_parquet, and a duckgres worker's RSS ratchets across the sequential
    sessions one run opens, so dropping this below 32Gi reintroduces the
    OOM-kill that shows up as a lost connection mid-registration.
    """
    options = registration_module._DUCKGRES_REGISTER_WORKER_OPTIONS
    match = re.search(r"duckgres\.worker_memory=(\d+)Gi", options)
    assert match is not None, f"worker_memory must be set in Gi: {options!r}"
    assert int(match.group(1)) >= 32, (
        f"registration worker memory is {match.group(1)}Gi, below the 32Gi floor: {options!r}"
    )


def _activity_inputs() -> DuckLakeRegisterDataImportsActivityInputs:
    return DuckLakeRegisterDataImportsActivityInputs(
        team_id=1,
        job_id="job",
        metadata=DuckLakeRegisterDataImportsMetadata(
            source_schema_id="schema",
            prepared_queryable_folder="customers__query_1234567890_abcdef12",
            prepared_source_uri="s3://source/team/customers__query_1234567890_abcdef12",
            landing_uri="s3://ducklake/posthog_data_imports_team_1/postgres_customers/_imports/schema/job",
            ducklake_schema_name="posthog_data_imports_team_1",
            ducklake_table_name="postgres_customers",
        ),
    )


def _workflow_inputs() -> DuckLakeRegisterDataImportsInputs:
    return DuckLakeRegisterDataImportsInputs(
        team_id=1,
        job_id="job",
        schema_id=uuid.UUID("019ef5df-e4c7-0000-b543-8ef7f13b5f15"),
        prepared_queryable_folder="customers__query",
    )


def _recorded_source_job_statuses(execute_activity: AsyncMock) -> list[ManagedWarehouseSourceJobStatus]:
    return [
        call.args[1].status
        for call in execute_activity.await_args_list
        if call.args[0] is registration_module.record_managed_warehouse_source_job_activity
    ]


def test_workflow_id_is_stable_for_one_schema():
    schema_id = "019ef5df-e4c7-0000-b543-8ef7f13b5f15"

    first = build_register_data_imports_workflow_id(team_id=473662, schema_id=schema_id)
    second = build_register_data_imports_workflow_id(team_id=473662, schema_id=schema_id)

    assert first == second
    assert first == f"ducklake-register-data-imports-473662-{schema_id}"


def test_workflow_id_differs_across_schemas():
    team_id = 473662

    first = build_register_data_imports_workflow_id(team_id=team_id, schema_id="019ef5df-e4c7-0000-b543-8ef7f13b5f15")
    second = build_register_data_imports_workflow_id(team_id=team_id, schema_id="019ef5df-e4c8-0000-b543-8ef7f13b5f16")

    assert first != second


ATTEMPT_TOKEN = "1790000000_a1b2c3d4e5f60718"
SHADOW_NAME = f"__ph_register_{ATTEMPT_TOKEN}"
MINTED_AT = dt.datetime(2026, 7, 30, 12, 0, 0, tzinfo=dt.UTC)


class _LocalFilesystem:
    def open(self, path: str, mode: str = "rb") -> Any:
        return open(path, mode)  # noqa: SIM115


class _FakeTimer:
    instances: list["_FakeTimer"] = []

    def __init__(self, interval: float, function: Callable[[], None]) -> None:
        self.interval = interval
        self.function = function
        self.daemon = False
        self.cancelled = False
        _FakeTimer.instances.append(self)

    def start(self) -> None:
        pass

    def cancel(self) -> None:
        self.cancelled = True


class _FakeTrinoCursor:
    def __init__(self, connection: "_FakeTrino") -> None:
        self._connection = connection
        self._rows: list[list[Any]] = []

    def execute(self, statement: str) -> None:
        self._connection.statements.append(statement)
        self._rows = self._connection.rows_for(statement)

    def fetchall(self) -> list[list[Any]]:
        return self._rows

    def cancel(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeTrino:
    catalog = "lake"

    def __init__(
        self,
        *,
        row_count: int = 1,
        publish_error: Exception | None = None,
        tables_after_failed_publish: list[str] | None = None,
        staging_tables: list[str] | None = None,
        on_statement: Callable[[str], None] | None = None,
    ) -> None:
        self.statements: list[str] = []
        self.row_count = row_count
        self.publish_error = publish_error
        self.tables_after_failed_publish = tables_after_failed_publish or []
        self.staging_tables = staging_tables or []
        self.on_statement = on_statement
        self.applied_import_ids: set[str] = set()

    def cursor(self) -> _FakeTrinoCursor:
        return _FakeTrinoCursor(self)

    def rows_for(self, statement: str) -> list[list[Any]]:
        if self.on_statement is not None:
            self.on_statement(statement)
        if "EXECUTE add_files" in statement:
            import_id = re.search(r"import_id => '([^']+)'", statement).group(1)  # type: ignore[union-attr]
            if import_id in self.applied_import_ids:
                return [["added_data_files", 0]]
            self.applied_import_ids.add(import_id)
            return [["added_data_files", len(re.findall(r"'[^']*\.parquet'", statement))]]
        if "EXECUTE publish_as" in statement and self.publish_error is not None:
            raise self.publish_error
        if statement.startswith("SELECT count(*)"):
            return [[self.row_count]]
        if "starts_with(table_name" in statement:
            return [[name] for name in self.staging_tables]
        if "information_schema.tables" in statement:
            return [[name] for name in self.tables_after_failed_publish]
        return []

    def statements_matching(self, text: str) -> list[str]:
        return [statement for statement in self.statements if text in statement]


def _rows(count: int) -> pa.Table:
    return pa.table({"id": pa.array(range(count), pa.int64())})


def _write_parquet_files(directory: Path, tables: dict[str, pa.Table]) -> list[str]:
    paths: list[str] = []
    for relative_path, table in tables.items():
        path = directory / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path)
        paths.append(str(path))
    return paths


def _register_through_trino(
    monkeypatch: pytest.MonkeyPatch,
    fake: _FakeTrino,
    directory: Path,
    tables: dict[str, pa.Table],
    *,
    hive_partition_columns: tuple[str, ...] = (),
    should_publish: bool = True,
    before_add_files_batch: Callable[[int, Sequence[str]], None] | None = None,
    deadline_monotonic: float | None = None,
    canary: bool = False,
) -> trino_module.TrinoRegistrationResult:
    connect = MagicMock(return_value=contextlib.nullcontext(fake))
    monkeypatch.setattr(trino_module, "connect_managed_warehouse_trino", connect)
    return trino_module.register_prepared_files_through_trino(
        organization_id="org",
        team_id=7,
        schema_id=uuid.UUID(int=5),
        ducklake_schema="schema_a",
        ducklake_table="table_a",
        shadow_name=SHADOW_NAME,
        attempt_token=ATTEMPT_TOKEN,
        landing_paths=_write_parquet_files(directory, tables),
        hive_partition_columns=hive_partition_columns,
        filesystem=_LocalFilesystem(),
        should_publish=lambda: should_publish,
        before_add_files_batch=before_add_files_batch,
        deadline_monotonic=deadline_monotonic,
        canary=canary,
    )


def _footer(path: str, **types: pa.DataType) -> trino_module.ParquetFooter:
    return trino_module.ParquetFooter(path=path, num_rows=1, schema=pa.schema(list(types.items())))


@pytest.mark.parametrize(
    "_name, hive_partition_columns, relative_paths, hive_partitioning",
    [
        ("unpartitioned", (), ["a.parquet", "b.parquet"], "false"),
        (
            "partitioned",
            ("_ph_partition_key",),
            ["_ph_partition_key=2026-07/a.parquet", "_ph_partition_key=2026-08/b.parquet"],
            "true",
        ),
    ],
)
@pytest.mark.parametrize("canary", [False, True])
def test_trino_registration_runs_the_expected_statements(
    canary: bool,
    _name: str,
    hive_partition_columns: tuple[str, ...],
    relative_paths: list[str],
    hive_partitioning: str,
    monkeypatch,
    tmp_path,
) -> None:
    table = pa.table(
        {
            "id": pa.array([1, 2], pa.int64()),
            "amount": pa.array([decimal.Decimal("1.50")] * 2, pa.decimal128(10, 2)),
            "created": pa.array([MINTED_AT] * 2, pa.timestamp("us", tz="UTC")),
            "note": pa.array(["a", "b"]),
        }
    )
    monkeypatch.setattr(trino_module, "add_files_batches", partial(trino_module.add_files_batches, max_files=1))
    fake = _FakeTrino(row_count=4)
    batches: list[tuple[int, list[str], int]] = []

    result = _register_through_trino(
        monkeypatch,
        fake,
        tmp_path,
        dict.fromkeys(relative_paths, table),
        hive_partition_columns=hive_partition_columns,
        before_add_files_batch=lambda index, paths: batches.append((index, list(paths), len(fake.statements))),
        canary=canary,
    )

    assert result == trino_module.TrinoRegistrationResult(published=True, row_count=4)
    assert cast(MagicMock, trino_module.connect_managed_warehouse_trino).call_args.kwargs["canary"] is canary
    create = fake.statements_matching("CREATE TABLE")[0]
    columns = '"id" BIGINT, "amount" DECIMAL(10, 2), "created" TIMESTAMP(6) WITH TIME ZONE, "note" VARCHAR' + (
        ', "_ph_partition_key" VARCHAR' if hive_partition_columns else ""
    )
    assert create.startswith(f'CREATE TABLE IF NOT EXISTS "lake"."schema_a"."{SHADOW_NAME}" ({columns})')
    assert "COMMENT" not in create
    if hive_partition_columns:
        assert create.endswith("WITH (partitioning = ARRAY['_ph_partition_key'])")
    else:
        assert "WITH (" not in create
    add_files = fake.statements_matching("EXECUTE add_files")
    sorted_paths = sorted(str(tmp_path / relative_path) for relative_path in relative_paths)
    assert len(add_files) == 2
    assert [(index, paths) for index, paths, _ in batches] == [(0, sorted_paths[:1]), (1, sorted_paths[1:])]
    assert [statements_before for _, _, statements_before in batches] == [
        fake.statements.index(statement) for statement in add_files
    ]
    assert fake.statements.index(create) < batches[0][2]
    assert f"import_id => '{ATTEMPT_TOKEN}_00000'" in add_files[0]
    assert f"import_id => '{ATTEMPT_TOKEN}_00001'" in add_files[1]
    assert all(f"hive_partitioning => {hive_partitioning}" in statement for statement in add_files)
    assert (
        fake.statements.index(add_files[-1])
        < fake.statements.index(fake.statements_matching("SELECT count(*)")[0])
        < len(fake.statements) - 1
    )
    assert fake.statements[-1] == (
        f'ALTER TABLE "lake"."schema_a"."{SHADOW_NAME}" EXECUTE publish_as(target => \'table_a\')'
    )


def test_trino_registration_replays_finished_batches_on_a_second_attempt(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(trino_module, "add_files_batches", partial(trino_module.add_files_batches, max_files=1))
    tables = {f"part-{index}.parquet": _rows(2) for index in range(3)}
    fake = _FakeTrino(row_count=6)

    _register_through_trino(monkeypatch, fake, tmp_path, tables)
    first_ids = re.findall(r"import_id => '([^']+)'", " ".join(fake.statements_matching("EXECUTE add_files")))
    fake.statements.clear()
    _register_through_trino(monkeypatch, fake, tmp_path, tables)
    second_ids = re.findall(r"import_id => '([^']+)'", " ".join(fake.statements_matching("EXECUTE add_files")))

    assert first_ids == [f"{ATTEMPT_TOKEN}_{index:05d}" for index in range(3)]
    assert second_ids == first_ids


def test_trino_registration_skips_publish_for_a_stale_generation(monkeypatch, tmp_path) -> None:
    fake = _FakeTrino(row_count=2)

    result = _register_through_trino(monkeypatch, fake, tmp_path, {"a.parquet": _rows(2)}, should_publish=False)

    assert result.published is False
    assert fake.statements_matching("publish_as") == []


@pytest.mark.parametrize(
    "_name, tables_present, counts_as_published",
    [
        ("shadow_gone_target_present", ["table_a"], True),
        ("shadow_still_present", [SHADOW_NAME], False),
    ],
)
def test_trino_registration_resolves_an_ambiguous_publish_failure(
    _name: str, tables_present: list[str], counts_as_published: bool, monkeypatch, tmp_path
) -> None:
    fake = _FakeTrino(
        row_count=2, publish_error=RuntimeError("response lost"), tables_after_failed_publish=tables_present
    )

    if counts_as_published:
        assert _register_through_trino(monkeypatch, fake, tmp_path, {"a.parquet": _rows(2)}).published is True
    else:
        with pytest.raises(RuntimeError, match="response lost"):
            _register_through_trino(monkeypatch, fake, tmp_path, {"a.parquet": _rows(2)})


@pytest.mark.parametrize(
    "_name, row_counts, registered, refuses",
    [
        ("same_count", [10, 5], 15, False),
        ("fewer_rows_registered", [10, 5], 14, True),
        ("more_rows_registered", [10, 5], 16, True),
        ("empty_registration_of_files_with_rows", [10], 0, True),
        ("empty_registration_of_empty_files", [0], 0, False),
    ],
)
def test_trino_registration_compares_row_counts_against_the_file_footers(
    _name: str, row_counts: list[int], registered: int, refuses: bool, monkeypatch, tmp_path
) -> None:
    fake = _FakeTrino(row_count=registered)
    tables = {f"part-{index}.parquet": _rows(count) for index, count in enumerate(row_counts)}

    if refuses:
        with pytest.raises(ApplicationError, match="row count mismatch") as error:
            _register_through_trino(monkeypatch, fake, tmp_path, tables)
        assert error.value.non_retryable is True
        assert fake.statements_matching("publish_as") == []
    else:
        assert _register_through_trino(monkeypatch, fake, tmp_path, tables).published is True


@pytest.mark.parametrize(
    "_name, arrow_type, expected",
    [
        ("utf8", pa.string(), "VARCHAR"),
        ("large_utf8", pa.large_string(), "VARCHAR"),
        ("utf8_view", pa.string_view(), "VARCHAR"),
        ("int64", pa.int64(), "BIGINT"),
        ("int32", pa.int32(), "INTEGER"),
        ("int16", pa.int16(), "SMALLINT"),
        ("int8", pa.int8(), "TINYINT"),
        ("float64", pa.float64(), "DOUBLE"),
        ("float32", pa.float32(), "REAL"),
        ("bool", pa.bool_(), "BOOLEAN"),
        ("date32", pa.date32(), "DATE"),
        ("binary", pa.binary(), "VARBINARY"),
        ("large_binary", pa.large_binary(), "VARBINARY"),
        ("binary_view", pa.binary_view(), "VARBINARY"),
        ("timestamp_us", pa.timestamp("us"), "TIMESTAMP(6)"),
        ("timestamp_us_tz", pa.timestamp("us", tz="UTC"), "TIMESTAMP(6) WITH TIME ZONE"),
        ("timestamp_us_named_tz", pa.timestamp("us", tz="America/New_York"), "TIMESTAMP(6) WITH TIME ZONE"),
        ("decimal", pa.decimal128(10, 2), "DECIMAL(10, 2)"),
        ("decimal_max", pa.decimal128(38, 18), "DECIMAL(38, 18)"),
        ("timestamp_ns", pa.timestamp("ns"), None),
        ("timestamp_ms", pa.timestamp("ms"), None),
        ("time", pa.time64("us"), None),
        ("duration", pa.duration("us"), None),
        ("date64", pa.date64(), None),
        ("uint32", pa.uint32(), None),
        ("null", pa.null(), None),
        ("decimal256_over_precision", pa.decimal256(40, 2), None),
        ("list", pa.list_(pa.int64()), None),
        ("struct", pa.struct([("a", pa.int64())]), None),
        ("dictionary", pa.dictionary(pa.int32(), pa.string()), None),
    ],
)
def test_trino_type_for_arrow(_name: str, arrow_type: pa.DataType, expected: str | None) -> None:
    assert trino_module.trino_type_for_arrow(arrow_type) == expected


def test_staging_schema_unions_file_columns_and_appends_hive_partitions() -> None:
    schema = trino_module.staging_table_schema(
        [
            _footer("a.parquet", id=pa.int64(), name=pa.string()),
            _footer("b.parquet", id=pa.int64(), name=pa.string_view(), created_at=pa.timestamp("us")),
        ],
        ["_ph_partition_key"],
    )

    assert schema.columns == (
        trino_module.StagingColumn(name="id", trino_type="BIGINT"),
        trino_module.StagingColumn(name="name", trino_type="VARCHAR"),
        trino_module.StagingColumn(name="created_at", trino_type="TIMESTAMP(6)"),
        trino_module.StagingColumn(name="_ph_partition_key", trino_type="VARCHAR"),
    )
    assert schema.partition_columns == ("_ph_partition_key",)


@pytest.mark.parametrize(
    "_name, footers, hive_columns, message",
    [
        ("unsupported_type", [_footer("a.parquet", at=pa.time64("us"))], [], "unsupported type"),
        (
            "conflicting_types",
            [_footer("a.parquet", id=pa.int32()), _footer("b.parquet", id=pa.int64())],
            [],
            "INTEGER in one file and BIGINT",
        ),
        (
            "case_folded_names",
            [_footer("a.parquet", id=pa.int64()), _footer("b.parquet", ID=pa.int64())],
            [],
            "differ only in case",
        ),
        ("partition_collides_with_column", [_footer("a.parquet", key=pa.string())], ["Key"], "collides with column"),
        ("partition_not_an_identifier", [_footer("a.parquet", id=pa.int64())], ["day(key)"], "not a plain identifier"),
    ],
)
def test_trino_registration_refuses_files_it_cannot_register_before_any_catalog_work(
    _name: str, footers: list[trino_module.ParquetFooter], hive_columns: list[str], message: str, monkeypatch
) -> None:
    connect = MagicMock()
    before_add_files_batch = MagicMock()
    monkeypatch.setattr(trino_module, "connect_managed_warehouse_trino", connect)
    monkeypatch.setattr(trino_module, "read_parquet_footers", lambda filesystem, paths: footers)

    with pytest.raises(ApplicationError, match=message) as error:
        trino_module.register_prepared_files_through_trino(
            organization_id="org",
            team_id=7,
            schema_id=uuid.UUID(int=5),
            ducklake_schema="schema_a",
            ducklake_table="table_a",
            shadow_name=SHADOW_NAME,
            attempt_token=ATTEMPT_TOKEN,
            landing_paths=[footer.path for footer in footers],
            hive_partition_columns=hive_columns,
            filesystem=_LocalFilesystem(),
            should_publish=lambda: True,
            before_add_files_batch=before_add_files_batch,
        )

    assert error.value.non_retryable is True
    connect.assert_not_called()
    before_add_files_batch.assert_not_called()


def test_read_parquet_footers_reads_row_counts_and_types_from_the_files(tmp_path) -> None:
    first = pa.table(
        {
            "id": pa.array([1, 2, 3], pa.int64()),
            "amount": pa.array([decimal.Decimal("1.50")] * 3, pa.decimal128(10, 2)),
            "at": pa.array([MINTED_AT] * 3, pa.timestamp("us", tz="UTC")),
        }
    )
    second = pa.table({"id": pa.array([4], pa.int64()), "note": pa.array(["x"], pa.large_string())})
    paths = _write_parquet_files(tmp_path, {"a.parquet": first, "b.parquet": second})

    footers = trino_module.read_parquet_footers(_LocalFilesystem(), paths)

    assert [(footer.path, footer.num_rows) for footer in footers] == [(paths[0], 3), (paths[1], 1)]
    assert trino_module.staging_table_schema(footers, []).columns == (
        trino_module.StagingColumn(name="id", trino_type="BIGINT"),
        trino_module.StagingColumn(name="amount", trino_type="DECIMAL(10, 2)"),
        trino_module.StagingColumn(name="at", trino_type="TIMESTAMP(6) WITH TIME ZONE"),
        trino_module.StagingColumn(name="note", trino_type="VARCHAR"),
    )


@pytest.mark.parametrize(
    "_name, file_count, max_characters, expected_sizes",
    [
        ("count_limit", 4001, 10_000_000, [2000, 2000, 1]),
        ("character_limit", 10, 3 * len("'s3://bucket/file-0000.parquet', "), [3, 3, 3, 1]),
    ],
)
def test_add_files_batches_bound_files_and_statement_size(
    _name: str, file_count: int, max_characters: int, expected_sizes: list[int]
) -> None:
    paths = [f"s3://bucket/file-{index:04d}.parquet" for index in range(file_count)]

    batches = trino_module.add_files_batches(paths, max_characters=max_characters)

    assert [len(batch) for batch in batches] == expected_sizes
    assert [path for batch in batches for path in batch] == paths


def test_stale_staging_tables_selects_old_tables_with_the_staging_name_up_to_the_limit() -> None:
    now = MINTED_AT
    names = [
        trino_module.staging_table_name(now - dt.timedelta(hours=7), "0" * 16),
        trino_module.staging_table_name(now - dt.timedelta(hours=1), "1" * 16),
        trino_module.staging_table_name(now - dt.timedelta(hours=8), "2" * 16),
        trino_module.staging_table_name(now - dt.timedelta(hours=9), "3" * 16),
        f"__ph_register_{uuid.UUID(int=1).hex}",
        "customers",
    ]

    stale = trino_module.stale_staging_tables(names, now=now, min_age=dt.timedelta(hours=6), limit=2)

    assert stale == [names[0], names[2]]
    assert re.fullmatch(r"__ph_register_\d{10}_[0-9a-f]{16}", names[0])


@pytest.mark.parametrize("canary", [False, True])
def test_trino_cleanup_drops_given_tables_and_sweeps_only_old_staging_tables(canary: bool, monkeypatch) -> None:
    now = dt.datetime.now(dt.UTC)
    old = trino_module.staging_table_name(now - dt.timedelta(hours=7), "0" * 16)
    young = trino_module.staging_table_name(now - dt.timedelta(hours=1), "1" * 16)
    legacy = f"__ph_register_{uuid.UUID(int=3).hex}"
    fake = _FakeTrino(staging_tables=[old, young, legacy])
    connect = MagicMock(return_value=contextlib.nullcontext(fake))
    monkeypatch.setattr(trino_module, "connect_managed_warehouse_trino", connect)

    trino_module.cleanup_trino_registration_tables(
        organization_id="org",
        team_id=7,
        schema_name="schema_a",
        table_names=["__ph_register_abc"],
        sweep_min_age=registration_module._SWEEP_MIN_AGE,
        sweep_limit=registration_module._SWEEP_BATCH_LIMIT,
        cancel_after_seconds=None,
        canary=canary,
    )

    assert connect.call_args.kwargs["canary"] is canary
    assert fake.statements == [
        'DROP TABLE IF EXISTS "lake"."schema_a"."__ph_register_abc"',
        "SELECT table_name FROM \"lake\".information_schema.tables WHERE table_schema = 'schema_a' "
        "AND starts_with(table_name, '__ph_register_')",
        f'DROP TABLE IF EXISTS "lake"."schema_a"."{old}"',
    ]


def test_trino_cleanup_runs_no_statement_after_the_activity_deadline(fake_timer, monkeypatch) -> None:
    fake = _FakeTrino(on_statement=lambda statement: fake_timer.instances[0].function())
    monkeypatch.setattr(
        trino_module, "connect_managed_warehouse_trino", MagicMock(return_value=contextlib.nullcontext(fake))
    )

    with pytest.raises(TimeoutError):
        trino_module.cleanup_trino_registration_tables(
            organization_id="org",
            team_id=7,
            schema_name="schema_a",
            table_names=["__ph_register_abc", "__ph_previous_abc"],
            sweep_min_age=registration_module._SWEEP_MIN_AGE,
            sweep_limit=registration_module._SWEEP_BATCH_LIMIT,
            cancel_after_seconds=60.0,
        )

    assert fake_timer.instances[0].interval == 60.0
    assert fake_timer.instances[0].cancelled is True
    assert fake.statements == ['DROP TABLE IF EXISTS "lake"."schema_a"."__ph_register_abc"']


@pytest.fixture
def fake_timer(monkeypatch) -> type[_FakeTimer]:
    _FakeTimer.instances = []
    monkeypatch.setattr(trino_module.threading, "Timer", _FakeTimer)
    return _FakeTimer


@pytest.mark.parametrize(
    "_name, deadline_during, failure, add_files_runs",
    [
        ("between_statements", "CREATE TABLE", None, 0),
        (
            "during_a_transient_failure",
            "EXECUTE add_files",
            TrinoUserError({"errorName": "CLUSTER_OUT_OF_MEMORY", "errorType": "INSUFFICIENT_RESOURCES"}, "query"),
            1,
        ),
    ],
)
@patch("tenacity.nap.time.sleep")
def test_trino_registration_stops_at_the_activity_deadline(
    _sleep,
    _name: str,
    deadline_during: str,
    failure: Exception | None,
    add_files_runs: int,
    fake_timer,
    monkeypatch,
    tmp_path,
) -> None:
    def on_statement(statement: str) -> None:
        if deadline_during in statement:
            fake_timer.instances[0].function()
            if failure is not None:
                raise failure

    fake = _FakeTrino(row_count=2, on_statement=on_statement)
    clock = [1_000.0]
    read_footers = trino_module.read_parquet_footers

    def slow_footer_reads(filesystem, paths):
        clock[0] += 30.0
        return read_footers(filesystem, paths)

    monkeypatch.setattr(trino_module, "monotonic", lambda: clock[0])
    monkeypatch.setattr(trino_module, "read_parquet_footers", slow_footer_reads)

    with pytest.raises(TimeoutError):
        _register_through_trino(monkeypatch, fake, tmp_path, {"a.parquet": _rows(2)}, deadline_monotonic=1_150.0)

    assert fake_timer.instances[0].interval == 120.0
    assert fake_timer.instances[0].cancelled is True
    assert len(fake.statements_matching("EXECUTE add_files")) == add_files_runs
    assert fake.statements_matching("publish_as") == []


def test_trino_registration_checks_whether_a_publish_committed_after_the_deadline_cancelled_it(
    fake_timer, monkeypatch, tmp_path
) -> None:
    fake = _FakeTrino(
        row_count=2,
        publish_error=RuntimeError("query canceled"),
        tables_after_failed_publish=["table_a"],
        on_statement=lambda statement: fake_timer.instances[0].function() if "publish_as" in statement else None,
    )

    result = _register_through_trino(
        monkeypatch, fake, tmp_path, {"a.parquet": _rows(2)}, deadline_monotonic=time.monotonic() + 120.0
    )

    assert result.published is True


def test_trino_registration_refuses_to_start_at_the_activity_deadline(fake_timer, monkeypatch, tmp_path) -> None:
    fake = _FakeTrino()

    with pytest.raises(TimeoutError, match="too close to the Temporal activity deadline"):
        _register_through_trino(
            monkeypatch, fake, tmp_path, {"a.parquet": _rows(2)}, deadline_monotonic=time.monotonic()
        )

    assert fake.statements == []
    assert fake_timer.instances == []


@pytest.mark.parametrize("trino_canary", [False, True])
def test_trino_cleanup_activity_dispatches_on_the_engine(trino_canary: bool, monkeypatch) -> None:
    cleanup = MagicMock()
    monkeypatch.setattr(registration_module, "cleanup_trino_registration_tables", cleanup)
    monkeypatch.setattr(registration_module, "_get_org_id_for_team", lambda team_id: "org")
    monkeypatch.setattr(registration_module, "_connect_to_duckgres_for_team", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(registration_module, "_duckgres_cancel_delay", lambda started: 42.0)

    registration_module.cleanup_ducklake_registration_tables_activity(
        registration_module.DuckLakeRegisterCleanupInputs(
            team_id=1,
            schema_name="schema_a",
            table_names=["__ph_register_abc"],
            engine=ENGINE_TRINO,
            trino_canary=trino_canary,
        )
    )

    assert cleanup.call_args.kwargs["table_names"] == ["__ph_register_abc"]
    assert cleanup.call_args.kwargs["organization_id"] == "org"
    assert cleanup.call_args.kwargs["canary"] is trino_canary
    assert cleanup.call_args.kwargs["cancel_after_seconds"] == 42.0


@pytest.mark.asyncio
@pytest.mark.parametrize("readiness_state", ["ready", "not_ready", "lookup_failed"])
@pytest.mark.parametrize("server_provisioned", [True, False])
@pytest.mark.parametrize("flag_enabled, override", [(True, None), (False, True)])
async def test_registration_gate_requires_a_ready_trino_target_and_ignores_the_duckgres_server(
    monkeypatch, server_provisioned, readiness_state, flag_enabled, override
) -> None:
    team = MagicMock(organization_id=uuid.UUID(int=9))
    monkeypatch.setattr(registration_module.Team.objects, "only", lambda *fields: MagicMock(get=lambda id: team))
    monkeypatch.setattr(registration_module, "feature_enabled_or_false", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        "products.managed_warehouse.backend.facade.access.background_loading_configured", lambda organization_id: False
    )
    monkeypatch.setattr(registration_module, "data_imports_trino_flag", lambda organization_id: flag_enabled)
    monkeypatch.setattr(registration_module, "is_dev_mode", lambda: False)
    monkeypatch.setattr(
        registration_module,
        "get_duckgres_server_by_team_org",
        lambda team_id: MagicMock() if server_provisioned else None,
    )
    readiness = MagicMock(
        return_value=TrinoTargetReadiness(
            catalog_name="tenant_catalog" if readiness_state == "ready" else None,
            lookup_failed=readiness_state == "lookup_failed",
        )
    )
    monkeypatch.setattr(registration_module, "get_trino_target_readiness", readiness)
    skipped_counter = MagicMock()
    skipped_metric = MagicMock(return_value=skipped_counter)
    monkeypatch.setattr(registration_module, "get_ducklake_register_data_imports_skipped_metric", skipped_metric)

    gate = ducklake_register_data_imports_gate_activity(
        DuckLakeRegisterDataImportsGateInputs(team_id=1, register_through_trino=override)
    )

    if readiness_state == "lookup_failed":
        with pytest.raises(ApplicationError, match="readiness check failed") as error:
            await gate
        assert error.value.non_retryable is False
    else:
        assert await gate is (readiness_state == "ready")
    readiness.assert_called_once_with(str(uuid.UUID(int=9)))
    if readiness_state == "not_ready":
        skipped_metric.assert_called_once_with(team_id=1, reason="trino_not_ready")
        skipped_counter.add.assert_called_once_with(1)
    else:
        skipped_metric.assert_not_called()


def test_trino_landing_uri_sits_under_the_data_path_with_the_job_and_generation() -> None:
    landing_uri = registration_module._trino_landing_uri(
        "s3://bucket/lake/",
        team_id=1,
        ducklake_schema_name="schema_a",
        ducklake_table_name="table_a",
        source_schema_id="schema-id",
        job_id="job/1",
        prepared_queryable_folder="customers__query_1234567890_abcdef12",
    )

    assert landing_uri == "s3://bucket/lake/_ph_imports/schema_a/table_a/schema-id/job_1/1234567890_abcdef12"

    with pytest.raises(ApplicationError) as error:
        registration_module._trino_landing_uri(
            None,
            team_id=1,
            ducklake_schema_name="schema_a",
            ducklake_table_name="table_a",
            source_schema_id="schema-id",
            job_id="job",
            prepared_queryable_folder="customers__query_1234567890_abcdef12",
        )
    assert error.value.non_retryable is False


@pytest.mark.parametrize("trino_canary", [True, False])
@pytest.mark.parametrize("names_minted_by_workflow", [True, False])
@pytest.mark.parametrize("published", [True, False])
def test_trino_copy_activity_copies_under_the_attempt_token_and_reports_staleness(
    monkeypatch, published, names_minted_by_workflow, trino_canary
) -> None:
    copy_calls: list[tuple[list[str], list[str]]] = []
    s3 = MagicMock()
    s3.find.side_effect = lambda prefix, detail=False: (
        {f"{prefix}/k=1/a.parquet": {"Size": 10, "type": "file"}} if detail else [f"{prefix}/k=1/a.parquet"]
    )
    s3.copy.side_effect = lambda sources, destinations, *, batch_size: copy_calls.append((sources, destinations))
    register = MagicMock(return_value=trino_module.TrinoRegistrationResult(published=published, row_count=3))
    monkeypatch.setattr(registration_module, "get_s3_client", lambda: s3)
    monkeypatch.setattr(registration_module, "register_prepared_files_through_trino", register)
    monkeypatch.setattr(registration_module, "_duckgres_cancel_delay", lambda started: 99.0)
    monkeypatch.setattr(registration_module, "_get_org_id_for_team", lambda team_id: "org")
    monkeypatch.setattr(registration_module, "HeartbeaterSync", lambda **kwargs: contextlib.nullcontext())
    _mock_activity_workload_metrics(monkeypatch)
    minted_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)
    base = _activity_inputs()
    inputs = dataclasses.replace(
        base,
        metadata=dataclasses.replace(
            base.metadata, engine=ENGINE_TRINO, source_schema_id=str(uuid.UUID(int=5)), trino_canary=trino_canary
        ),
        registration_table_names=(
            registration_module._new_trino_registration_table_names(minted_at, "a1b2c3d4e5f60718")
            if names_minted_by_workflow
            else None
        ),
    )

    applied = copy_and_register_ducklake_data_imports_activity(inputs)

    assert applied is published
    kwargs = register.call_args.kwargs
    assert re.fullmatch(r"__ph_register_\d{10}_[0-9a-f]{16}", kwargs["shadow_name"])
    assert kwargs["attempt_token"] == kwargs["shadow_name"].removeprefix("__ph_register_")
    if names_minted_by_workflow:
        assert kwargs["attempt_token"] == f"{int(minted_at.timestamp())}_a1b2c3d4e5f60718"
    attempt_prefix = (
        "ducklake/posthog_data_imports_team_1/postgres_customers/_imports/schema/job/"
        f"1234567890_abcdef12/{kwargs['attempt_token']}"
    )
    landing_prefix = re.fullmatch(rf"({re.escape(attempt_prefix)}/m[0-9a-f]{{16}})/k=1/a\.parquet", copy_calls[0][1][0])
    assert landing_prefix
    assert kwargs["landing_paths"] == [f"s3://{landing_prefix.group(1)}/k=1/a.parquet"]
    assert kwargs["hive_partition_columns"] == ["k"]
    assert kwargs["filesystem"] is s3
    assert kwargs["canary"] is trino_canary
    assert kwargs["deadline_monotonic"] == pytest.approx(time.monotonic() + 99.0, abs=30.0)


class _FakeS3:
    def __init__(self, keys: set[str], *, partial_copy_fails: bool = False, rm_mode: str = "works") -> None:
        self.keys = set(keys)
        self.partial_copy_fails = partial_copy_fails
        self.rm_mode = rm_mode
        self.copy_destinations: list[str] = []
        self.bodies: dict[str, bytes] = {}

    def pipe_file(self, path: str, value: bytes) -> None:
        self.keys.add(path)
        self.bodies[path] = value

    def cat_file(self, path: str) -> bytes:
        return self.bodies[path]

    def invalidate_cache(self, path: str | None = None) -> None:
        pass

    def find(self, prefix: str, detail: bool = False) -> Any:
        folder = prefix.rstrip("/") + "/"
        found = sorted(key for key in self.keys if key.startswith(folder))
        return {key: {"Size": 10, "type": "file"} for key in found} if detail else found

    def copy(self, sources: list[str], destinations: list[str], *, batch_size: int) -> None:
        copied = destinations[:1] if self.partial_copy_fails else destinations
        self.keys.update(copied)
        self.copy_destinations.extend(copied)
        if self.partial_copy_fails:
            raise RuntimeError("copy failed")

    def rm(self, paths: list[str]) -> None:
        if self.rm_mode == "raises":
            raise RuntimeError("delete failed")
        if self.rm_mode == "works":
            self.keys.difference_update(paths)
            for path in paths:
                self.bodies.pop(path, None)


@pytest.mark.parametrize(
    "registration, partial_copy_fails, rm_mode, expected_error, expected_result, files_deleted",
    [
        pytest.param(
            "fails_before_add_files", False, "works", "footer type error", None, True, id="fails_before_add_files"
        ),
        pytest.param("fails_before_add_files", True, "works", "copy failed", None, True, id="partial_copy_raises"),
        pytest.param(
            "fails_after_add_files_started",
            False,
            "works",
            "add files failed",
            None,
            False,
            id="fails_after_add_files_started",
        ),
        pytest.param("unpublished", False, "works", None, False, False, id="stale_skip"),
        pytest.param("published", False, "works", None, True, False, id="published"),
        pytest.param("fails_before_add_files", False, "raises", "footer type error", None, False, id="rm_raises"),
        pytest.param(
            "fails_before_add_files", False, "does_nothing", "footer type error", None, False, id="rm_leaves_files"
        ),
    ],
)
def test_trino_copy_activity_deletes_its_files_only_before_it_adds_any(
    monkeypatch, registration, partial_copy_fails, rm_mode, expected_error, expected_result, files_deleted
) -> None:
    base = _activity_inputs()
    source_prefix = base.metadata.prepared_source_uri.removeprefix("s3://").rstrip("/")
    source_keys = {f"{source_prefix}/k=1/a.parquet", f"{source_prefix}/k=2/b.parquet"}
    fake_s3 = _FakeS3(source_keys, partial_copy_fails=partial_copy_fails, rm_mode=rm_mode)
    capture = MagicMock()
    first_batch: list[str] = []

    def fake_register(**kwargs: Any) -> trino_module.TrinoRegistrationResult:
        if registration == "fails_before_add_files":
            raise ApplicationError("footer type error", non_retryable=True)
        first_batch.extend(kwargs["landing_paths"][:1])
        kwargs["before_add_files_batch"](0, first_batch)
        if registration == "fails_after_add_files_started":
            raise RuntimeError("add files failed")
        return trino_module.TrinoRegistrationResult(published=registration == "published", row_count=3)

    monkeypatch.setattr(registration_module, "get_s3_client", lambda: fake_s3)
    monkeypatch.setattr(registration_module, "capture_exception", capture)
    monkeypatch.setattr(
        registration_module, "register_prepared_files_through_trino", MagicMock(side_effect=fake_register)
    )
    monkeypatch.setattr(registration_module, "_should_publish_prepared_generation", lambda inputs: True)
    monkeypatch.setattr(registration_module, "_duckgres_cancel_delay", lambda started: 99.0)
    monkeypatch.setattr(registration_module, "_get_org_id_for_team", lambda team_id: "org")
    monkeypatch.setattr(registration_module, "HeartbeaterSync", lambda **kwargs: contextlib.nullcontext())
    _mock_activity_workload_metrics(monkeypatch)
    inputs = dataclasses.replace(
        base,
        metadata=dataclasses.replace(base.metadata, engine=ENGINE_TRINO, source_schema_id=str(uuid.UUID(int=5))),
        registration_table_names=registration_module._new_trino_registration_table_names(
            dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5), "a1b2c3d4e5f60718"
        ),
    )

    if expected_error is not None:
        with pytest.raises((ApplicationError, RuntimeError), match=expected_error):
            copy_and_register_ducklake_data_imports_activity(inputs)
    else:
        assert copy_and_register_ducklake_data_imports_activity(inputs) is expected_result

    assert source_keys <= fake_s3.keys
    if registration != "fails_before_add_files":
        execution_folder = fake_s3.copy_destinations[0].split("/k=")[0]
        assert fake_s3.bodies.keys() == {f"{execution_folder}/_ph_add_files/00000.json"}
        assert json.loads(next(iter(fake_s3.bodies.values()))) == {"files": first_batch}
    else:
        assert fake_s3.bodies == {}
    if files_deleted:
        assert fake_s3.keys == source_keys
    else:
        assert fake_s3.copy_destinations
        assert set(fake_s3.copy_destinations) <= fake_s3.keys
    if rm_mode == "does_nothing":
        capture.assert_called_once()
        assert isinstance(capture.call_args.args[0], RuntimeError)


def test_trino_copy_activity_refuses_names_older_than_the_start_delay(monkeypatch) -> None:
    s3 = MagicMock()
    register = MagicMock()
    monkeypatch.setattr(registration_module, "get_s3_client", lambda: s3)
    monkeypatch.setattr(registration_module, "register_prepared_files_through_trino", register)
    monkeypatch.setattr(registration_module, "_get_org_id_for_team", lambda team_id: "org")
    monkeypatch.setattr(registration_module, "HeartbeaterSync", lambda **kwargs: contextlib.nullcontext())
    _mock_activity_workload_metrics(monkeypatch)
    minted_at = dt.datetime.now(dt.UTC) - registration_module._TRINO_MAX_START_DELAY - dt.timedelta(minutes=5)
    base = _activity_inputs()
    inputs = dataclasses.replace(
        base,
        metadata=dataclasses.replace(base.metadata, engine=ENGINE_TRINO, source_schema_id=str(uuid.UUID(int=5))),
        registration_table_names=registration_module._new_trino_registration_table_names(minted_at, "a1b2c3d4e5f60718"),
    )

    with pytest.raises(ApplicationError, match="stale-table sweep") as error:
        copy_and_register_ducklake_data_imports_activity(inputs)

    assert error.value.non_retryable is True
    s3.copy.assert_not_called()
    register.assert_not_called()


@pytest.mark.asyncio
async def test_workflow_mints_time_stamped_staging_names_for_trino(monkeypatch) -> None:
    finished_at = MINTED_AT + dt.timedelta(minutes=7)
    metadata = dataclasses.replace(_activity_inputs().metadata, engine=ENGINE_TRINO, trino_canary=True)
    execute_activity = AsyncMock(side_effect=[True, None, metadata, True, None, None])
    _mock_workflow_metrics(monkeypatch)
    monkeypatch.setattr(registration_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(registration_module.workflow, "uuid4", MagicMock(return_value=uuid.UUID(int=7)))
    monkeypatch.setattr(
        registration_module.workflow, "now", MagicMock(side_effect=[MINTED_AT, MINTED_AT, finished_at, finished_at])
    )

    await DuckLakeRegisterDataImportsWorkflow().run(
        dataclasses.replace(_workflow_inputs(), register_through_trino=True)
    )

    gate_call = execute_activity.await_args_list[0]
    assert gate_call.args[1].register_through_trino is True
    copy_call = next(
        call
        for call in execute_activity.await_args_list
        if call.args[0] is copy_and_register_ducklake_data_imports_activity
    )
    cleanup_call = next(
        call
        for call in execute_activity.await_args_list
        if call.args[0] is registration_module.cleanup_ducklake_registration_tables_activity
    )
    names = copy_call.args[1].registration_table_names
    assert names.shadow_name == trino_module.staging_table_name(MINTED_AT, uuid.UUID(int=7).hex[:16])
    assert cleanup_call.args[1].engine == ENGINE_TRINO
    assert cleanup_call.args[1].trino_canary is True
    assert names.shadow_name in cleanup_call.args[1].table_names


@pytest.mark.parametrize(
    "_name, trino_flag, dev_mode, server, override, expected",
    [
        ("trino", True, False, None, None, ENGINE_TRINO),
        ("duckgres_with_a_server", False, False, MagicMock(), None, ENGINE_DUCKGRES),
        ("duckgres_in_dev_mode_without_a_server", False, True, None, None, ENGINE_DUCKGRES),
        ("unconfirmed_without_a_server", False, False, None, None, None),
        ("override_trino_without_flag_or_server", False, False, None, True, ENGINE_TRINO),
        ("override_duckgres_with_flag_and_server", True, False, MagicMock(), False, ENGINE_DUCKGRES),
    ],
)
@pytest.mark.asyncio
async def test_registration_engine_retries_instead_of_falling_back_for_an_org_without_a_server(
    _name: str,
    trino_flag: bool,
    dev_mode: bool,
    server: Any,
    override: bool | None,
    expected: str | None,
    monkeypatch,
) -> None:
    monkeypatch.setattr(registration_module, "data_imports_through_trino", lambda organization_id: trino_flag)
    monkeypatch.setattr(registration_module, "is_dev_mode", lambda: dev_mode)
    monkeypatch.setattr(registration_module, "get_duckgres_server_by_team_org", lambda team_id: server)

    if expected is None:
        with pytest.raises(ApplicationError, match="could not be confirmed") as error:
            await registration_module._registration_engine_for_team(1, "org", override)
        assert error.value.non_retryable is False
    else:
        assert await registration_module._registration_engine_for_team(1, "org", override) == expected


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "register_through_trino, use_trino_canary, expected_engine, expected_canary",
    [
        (None, False, ENGINE_TRINO, False),
        (None, True, ENGINE_TRINO, True),
        (True, True, ENGINE_TRINO, True),
        (False, True, ENGINE_DUCKGRES, False),
    ],
)
async def test_prepare_registration_stamps_the_engine_and_canary_and_lands_trino_under_the_data_path(
    monkeypatch, ateam, register_through_trino, use_trino_canary, expected_engine, expected_canary
):
    monkeypatch.setattr(registration_module, "data_imports_through_trino", lambda organization_id: True)
    monkeypatch.setattr(registration_module, "_resolve_data_imports_landing_uri", lambda **kwargs: "s3://duckgres/path")
    monkeypatch.setattr(registration_module, "get_control_plane_data_path", lambda organization_id: "s3://bucket/lake/")
    credential = await database_sync_to_async(DataWarehouseCredential.objects.create)(
        team=ateam, access_key="test_key", access_secret="test_secret"
    )
    source = await database_sync_to_async(ExternalDataSource.objects.create)(
        team=ateam, source_id="source", connection_id="connection", source_type="Postgres", status="Running"
    )
    prepared_queryable_folder = "customers__query_1234567890_abcdef12"
    table = await database_sync_to_async(DataWarehouseTable.objects.create)(
        team=ateam,
        name="customers",
        format="Delta",
        url_pattern="s3://bucket/path",
        credential=credential,
        external_data_source=source,
        columns={"id": {"clickhouse": "Int64", "hogql": "IntegerDatabaseField"}},
        queryable_folder=prepared_queryable_folder,
    )
    schema = await database_sync_to_async(ExternalDataSchema.objects.create)(
        team=ateam, name="customers", source=source, table=table
    )

    metadata = await prepare_ducklake_data_imports_registration_activity(
        DuckLakeRegisterDataImportsInputs(
            team_id=ateam.id,
            job_id="job-123",
            schema_id=schema.id,
            prepared_queryable_folder=prepared_queryable_folder,
            register_through_trino=register_through_trino,
            use_trino_canary=use_trino_canary,
        )
    )

    assert metadata is not None
    assert metadata.engine == expected_engine
    assert metadata.trino_canary is expected_canary
    if expected_engine == ENGINE_TRINO:
        assert metadata.landing_uri == (
            f"s3://bucket/lake/_ph_imports/posthog_data_imports_team_{ateam.id}/postgres_customers/"
            f"{schema.id}/job-123/1234567890_abcdef12"
        )


@pytest.mark.parametrize(
    "extra, expected_override, expected_canary",
    [
        ({}, None, False),
        ({"register_through_trino": True, "use_trino_canary": True}, True, True),
        ({"register_through_trino": False}, False, False),
    ],
)
def test_parse_inputs_reads_the_engine_override_and_keeps_old_json_valid(
    extra: dict[str, Any], expected_override: bool | None, expected_canary: bool
) -> None:
    payload = {
        "team_id": 1,
        "job_id": "job",
        "schema_id": "019ef5df-e4c7-0000-b543-8ef7f13b5f15",
        "prepared_queryable_folder": "customers__query",
        **extra,
    }

    inputs = DuckLakeRegisterDataImportsWorkflow.parse_inputs([json.dumps(payload)])

    assert inputs.register_through_trino is expected_override
    assert inputs.use_trino_canary is expected_canary


@pytest.mark.parametrize(
    "scenario",
    [
        "unregistered_after_worker_loss",
        "partially_registered",
        "older_execution_without_manifests",
        "attempt_may_still_run",
        "manifest_lists_a_file_outside_its_execution",
        "not_a_landing_folder",
        "glob_like_name",
    ],
)
def test_landing_sweep_activity_deletes_only_files_no_manifest_lists(monkeypatch, scenario) -> None:
    age = (
        dt.timedelta(hours=5)
        if scenario == "attempt_may_still_run"
        else registration_module._SWEEP_MIN_AGE + dt.timedelta(minutes=1)
    )
    minted = int((dt.datetime.now(dt.UTC) - age).timestamp())
    token = f"{minted}_a1b2c3d4e5f60718"
    sibling_token = f"{minted}_0000000000000001"
    root = "imports" if scenario == "not_a_landing_folder" else "_ph_imports"
    generation = f"ducklake/{root}/schema_a/table_a/schema-id/job/1234567890_abcdef12"
    folder = "0123456789abcdef" if scenario == "older_execution_without_manifests" else "m0123456789abcdef"
    execution = f"{generation}/{token}/{folder}"
    sibling = f"{generation}/{sibling_token}/m0123456789abcdef/a.parquet"
    files = [f"{execution}/a.parquet", f"{execution}/k=1/b.parquet"]
    manifest_entries: list[str] = []
    expected_deleted: set[str] = set()
    if scenario == "unregistered_after_worker_loss":
        expected_deleted = set(files)
    if scenario == "partially_registered":
        second_execution_file = f"{generation}/{token}/mfedcba9876543210/e.parquet"
        files += [f"{execution}/c.parquet", f"{execution}/k=2/d.parquet", second_execution_file]
        manifest_entries = files[:2]
        expected_deleted = set(files[2:])
    if scenario == "manifest_lists_a_file_outside_its_execution":
        manifest_entries = [f"{generation}/{token}/mfedcba9876543210/a.parquet"]
    if scenario == "glob_like_name":
        files = [f"{execution}/k=[1]/x.parquet", f"{execution}/k=1/x.parquet"]
        manifest_entries = [files[1]]
    fake_s3 = _FakeS3({sibling, *files})
    if manifest_entries:
        landing_module.write_batch_manifest(
            fake_s3, f"s3://{execution}", 0, [f"s3://{entry}" for entry in manifest_entries]
        )
    monkeypatch.setattr(registration_module, "get_s3_client", lambda: fake_s3)
    inputs = DuckLakeTrinoLandingSweepInputs(
        team_id=1, attempt_uri=f"s3://{generation}/{token}", delete_after=dt.datetime.now(dt.UTC)
    )
    before = set(fake_s3.keys)

    if scenario in ("attempt_may_still_run", "manifest_lists_a_file_outside_its_execution", "not_a_landing_folder"):
        with pytest.raises(ApplicationError) as error:
            registration_module.sweep_trino_registration_landing_activity(inputs)
        assert error.value.non_retryable is (scenario != "attempt_may_still_run")
        assert fake_s3.keys == before
        return
    registration_module.sweep_trino_registration_landing_activity(inputs)

    assert fake_s3.keys == before - expected_deleted


def test_landing_sweep_keeps_the_files_the_copy_activity_manifested(monkeypatch) -> None:
    base = _activity_inputs()
    source_prefix = base.metadata.prepared_source_uri.removeprefix("s3://").rstrip("/")
    source_keys = {f"{source_prefix}/k=1/a.parquet", f"{source_prefix}/k=2/b.parquet"}
    fake_s3 = _FakeS3(source_keys)

    def fake_register(**kwargs: Any) -> trino_module.TrinoRegistrationResult:
        kwargs["before_add_files_batch"](0, kwargs["landing_paths"][:1])
        raise RuntimeError("the activity died after one batch")

    monkeypatch.setattr(registration_module, "get_s3_client", lambda: fake_s3)
    monkeypatch.setattr(
        registration_module, "register_prepared_files_through_trino", MagicMock(side_effect=fake_register)
    )
    monkeypatch.setattr(registration_module, "_duckgres_cancel_delay", lambda started: 99.0)
    monkeypatch.setattr(registration_module, "_get_org_id_for_team", lambda team_id: "org")
    monkeypatch.setattr(registration_module, "HeartbeaterSync", lambda **kwargs: contextlib.nullcontext())
    _mock_activity_workload_metrics(monkeypatch)
    names = registration_module._new_trino_registration_table_names(
        dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5), "a1b2c3d4e5f60718"
    )
    inputs = dataclasses.replace(
        base,
        metadata=dataclasses.replace(
            base.metadata,
            engine=ENGINE_TRINO,
            source_schema_id=str(uuid.UUID(int=5)),
            landing_uri="s3://ducklake/_ph_imports/schema_a/table_a/schema/job",
        ),
        registration_table_names=names,
    )
    token = names.shadow_name.removeprefix("__ph_register_")

    with pytest.raises(RuntimeError, match="died after one batch"):
        copy_and_register_ducklake_data_imports_activity(inputs)
    first, second = fake_s3.copy_destinations
    execution_folder = first.split("/k=")[0]
    attempt_uri = "s3://" + execution_folder.rsplit("/", 1)[0]
    assert attempt_uri.endswith(f"/{token}")
    landing_module.sweep_unregistered_landing_files(
        fake_s3,
        attempt_uri,
        now=dt.datetime.now(dt.UTC) + registration_module._SWEEP_MIN_AGE + dt.timedelta(minutes=10),
        min_age=registration_module._SWEEP_MIN_AGE,
    )

    assert fake_s3.keys == source_keys | {first, f"{execution_folder}/_ph_add_files/00000.json"}
    assert second not in fake_s3.keys
