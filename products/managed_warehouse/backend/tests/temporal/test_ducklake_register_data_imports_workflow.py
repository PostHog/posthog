import uuid
import datetime as dt
import contextlib
import dataclasses
from collections.abc import Iterator

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.sync import database_sync_to_async

from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseSourceJobStatus
from products.managed_warehouse.backend.temporal import ducklake_register_data_imports_workflow as registration_module
from products.managed_warehouse.backend.temporal.ducklake_register_data_imports_workflow import (
    S3_COPY_BATCH_SIZE,
    DuckLakeRegisterDataImportsActivityInputs,
    DuckLakeRegisterDataImportsGateInputs,
    DuckLakeRegisterDataImportsInputs,
    DuckLakeRegisterDataImportsMetadata,
    DuckLakeRegisterDataImportsWorkflow,
    build_register_data_imports_workflow_id,
    copy_and_register_ducklake_data_imports_activity,
    ducklake_register_data_imports_gate_activity,
    prepare_ducklake_data_imports_registration_activity,
)
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


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("flag_enabled", [True, False])
async def test_registration_gate_uses_data_warehouse_scene_flag(monkeypatch, ateam, flag_enabled):
    captured: dict[str, object] = {}

    def fake_feature_enabled(key, distinct_id, **kwargs):
        captured.update(key=key, distinct_id=distinct_id, **kwargs)
        return flag_enabled

    monkeypatch.setattr(registration_module, "feature_enabled_or_false", fake_feature_enabled)

    result = await ducklake_register_data_imports_gate_activity(DuckLakeRegisterDataImportsGateInputs(team_id=ateam.id))

    assert result is flag_enabled
    assert captured["key"] == "data-warehouse-scene"
    assert captured["distinct_id"] == str(ateam.organization_id)
    assert captured["groups"] == {"organization": str(ateam.organization_id)}
    assert captured["group_properties"] == {"organization": {"id": str(ateam.organization_id)}}
    assert captured["only_evaluate_locally"] is True
    assert captured["send_feature_flag_events"] is False


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize("server_provisioned", [True, False])
async def test_registration_gate_requires_provisioned_duckgres_server(monkeypatch, ateam, server_provisioned):
    monkeypatch.setattr(registration_module, "feature_enabled_or_false", lambda *args, **kwargs: True)
    monkeypatch.setattr(registration_module, "is_dev_mode", lambda: False)
    monkeypatch.setattr(
        registration_module,
        "get_duckgres_server_by_team_org",
        lambda team_id: MagicMock() if server_provisioned else None,
    )

    result = await ducklake_register_data_imports_gate_activity(DuckLakeRegisterDataImportsGateInputs(team_id=ateam.id))

    assert result is server_provisioned


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
        options="-c duckgres.worker_cpu=4 -c duckgres.worker_memory=16Gi",
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
        options="-c duckgres.worker_cpu=4 -c duckgres.worker_memory=16Gi",
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
async def test_workflow_cleanup_finalizer_runs_when_copy_activity_fails(monkeypatch):
    started_at = dt.datetime(2026, 7, 30, 12, 0, 0)
    failed_at = started_at + dt.timedelta(minutes=3)
    execute_activity = AsyncMock(
        side_effect=[
            True,
            None,
            _activity_inputs().metadata,
            RuntimeError("register worker died"),
            None,
            None,
        ]
    )
    _mock_workflow_metrics(monkeypatch)
    monkeypatch.setattr(registration_module.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(registration_module.workflow, "uuid4", MagicMock(return_value=uuid.UUID(int=9)))
    monkeypatch.setattr(
        registration_module.workflow,
        "now",
        MagicMock(side_effect=[started_at, failed_at, failed_at]),
    )

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
