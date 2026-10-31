from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import uuid4

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from django.conf import settings

import duckdb
import psycopg
from dagster import DagsterInstance, DagsterRun, DagsterRunStatus, SensorResult, build_sensor_context, materialize
from psycopg import sql

from posthog.clickhouse.client.connection import get_client_from_pool
from posthog.dags.events_backfill_to_duckling import DUCKLAKE_ALIAS, DucklingBackfillConfig, DucklingTarget

from products.managed_warehouse.backend.facade.contracts import (
    DuckLakeDayReplacement,
    DuckLakeTableReplacement,
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)
from products.managed_warehouse.dags.groups_backfill import (
    GROUPS_JOB_NAME,
    GROUPS_REFRESH_DATE_TAG,
    GROUPS_SNAPSHOT_TAG,
    GROUPS_TRINO_COLUMN_TYPES,
    MAX_TEAMS_PER_TICK,
    RETRY_BASE_SECONDS,
    duckling_groups_backfill,
    duckling_groups_daily_backfill_sensor,
    duckling_groups_full_backfill_sensor,
    ensure_groups_table,
    export_groups_to_duckling_s3,
    groups_snapshot_select_sql,
    run_groups_backfill,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dagster import RunRequest


@pytest.mark.parametrize("for_trino", [False, True])
@pytest.mark.parametrize("partition_date", [None, datetime(2025, 1, 1), datetime(2025, 1, 2), datetime(2025, 1, 3)])
def test_groups_snapshot_deduplicates_keys_within_each_team_and_group_type(
    monkeypatch: pytest.MonkeyPatch, partition_date: datetime | None, for_trino: bool
) -> None:
    monkeypatch.setattr(settings, "CLICKHOUSE_USE_HTTP", False)
    table_name = f"test_groups_snapshot_{uuid4().hex}"
    with get_client_from_pool() as client:
        client.execute(f"""
            CREATE TABLE {table_name} (
                team_id Int64, group_type_index UInt8, group_key String, group_properties String,
                created_at DateTime64(3), _timestamp DateTime, _offset UInt64
            ) ENGINE = ReplacingMergeTree(_timestamp)
            ORDER BY (team_id, group_type_index, group_key)
        """)
        try:
            client.execute(f"SYSTEM STOP MERGES {table_name}")
            created = datetime(2025, 1, 1)
            latest = datetime(2025, 1, 2)
            client.execute(
                f"INSERT INTO {table_name} VALUES",
                [
                    (7, 0, "company", '{"name":"latest"}', created, latest, 2),
                    (7, 0, "tied", '{"name":"first insert"}', created, latest, 99),
                    (7, 1, "company", '{"name":"another type"}', created, latest, 2),
                    (8, 0, "company", '{"name":"another team"}', created, latest, 2),
                ],
            )
            client.execute(
                f"INSERT INTO {table_name} VALUES",
                [
                    (7, 0, "company", '{"name":"old"}', created, created, 1),
                    (7, 0, "tied", '{"name":"last insert"}', created, latest, 1),
                ],
            )
            query = groups_snapshot_select_sql(7, partition_date, for_trino=for_trino).replace(
                "FROM groups FINAL", f"FROM {table_name} FINAL"
            )
            rows = client.execute(query)
            described = {str(row[0]): str(row[1]) for row in client.execute(f"DESCRIBE ({query})")}
        finally:
            client.execute(f"DROP TABLE {table_name}")
    expected = [
        (7, 0, "company", '{"name":"latest"}', created, latest),
        (7, 0, "tied", '{"name":"last insert"}', created, latest),
        (7, 1, "company", '{"name":"another type"}', created, latest),
    ]
    assert sorted((*row[:4], row[4].replace(tzinfo=None), row[5]) for row in rows) == [
        row for row in expected if partition_date is None or row[5] == partition_date
    ]
    if for_trino:
        # add_files refuses any type conversion, so these must be the types DuckLake writes for the Trino columns.
        assert described == {
            "team_id": "Int64",
            "group_type_index": "Int16",
            "group_key": "String",
            "group_properties": "String",
            "created_at": "DateTime64(6, 'UTC')",
            "_timestamp": "DateTime64(6)",
            "_inserted_at": "DateTime64(6)",
        }


@pytest.mark.parametrize("memory_override", [None, 20 * 1024**3])
@pytest.mark.parametrize("partition_date", [None, datetime(2025, 1, 2)])
def test_groups_export_memory_default_and_operator_override(
    memory_override: int | None, partition_date: datetime | None
) -> None:
    client = MagicMock()
    client.execute.return_value = [(100,)]
    context = MagicMock()
    context.run.run_id = "synthetic-run"
    target = DucklingTarget(team_id=7, organization_id="org", bucket="unused", bucket_region="us-east-1")
    config = DucklingBackfillConfig(
        clickhouse_settings={"max_memory_usage": memory_override} if memory_override is not None else None
    )

    with patch(
        "products.managed_warehouse.dags.groups_backfill.get_s3_url_for_clickhouse", return_value="https://example.com"
    ):
        result = export_groups_to_duckling_s3(context, client, config, target, partition_date)

    export_query = client.execute.call_args.args[0]
    export_settings = client.execute.call_args.kwargs["settings"]
    period = "/2025-01-02" if partition_date is not None else ""
    assert result == f"s3://unused/backfill/groups/7{period}/synthetic-run/*.parquet"
    assert "FROM groups FINAL" in export_query
    assert "ORDER BY" not in export_query
    assert export_settings["max_memory_usage"] == (memory_override if memory_override is not None else 100 * 1024**3)


class _LakeConnection:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self.connection = connection

    def execute(self, query: str | sql.Composable, params: tuple[object, ...] | None = None) -> _LakeConnection:
        statement = query.as_string() if isinstance(query, sql.Composable) else query
        self.connection.execute(statement.replace("%s", "?"), params)
        return self

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.connection.fetchall()

    def cursor(self) -> _LakeConnection:
        return self

    def __enter__(self) -> _LakeConnection:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def close(self) -> None:
        pass


@pytest.fixture
def lake(tmp_path: Path) -> Iterator[psycopg.Connection[tuple[object, ...]]]:
    connection = duckdb.connect()
    connection.execute("INSTALL ducklake")
    connection.execute("LOAD ducklake")
    connection.execute(
        f"ATTACH 'ducklake:{tmp_path / 'catalog.ducklake'}' AS {DUCKLAKE_ALIAS} (DATA_PATH '{tmp_path / 'data'}')"
    )
    adapter = cast(psycopg.Connection[tuple[object, ...]], _LakeConnection(connection))
    ensure_groups_table(adapter, "groups_production", DucklingBackfillConfig())
    yield adapter
    connection.close()


@pytest.mark.parametrize(
    "scenario",
    [
        "success",
        "partial_disconnect",
        "committed_disconnect",
        "invalid_file",
        "export_failure",
        "empty",
        "append",
        "dry_run",
        "skip_registration",
    ],
)
@pytest.mark.parametrize("daily", [False, True])
@time_machine.travel(datetime(2026, 1, 1, tzinfo=UTC), tick=False)
def test_groups_backfill_cleans_only_its_partition_and_replays_registration(
    lake: psycopg.Connection[tuple[object, ...]], tmp_path: Path, scenario: str, daily: bool
) -> None:
    table = f"{DUCKLAKE_ALIAS}.posthog.groups_production"
    target = DucklingTarget(team_id=7, organization_id="org", bucket="unused", bucket_region="us-east-1")
    date = datetime(2025, 12, 31, tzinfo=UTC)
    lake.execute(
        f"INSERT INTO {table} (team_id, group_type_index, group_key, _timestamp) VALUES (%s, %s, %s, %s)",
        (7, 0, "old", date),
    )
    for team, key, timestamp in [
        (7, "before", date - timedelta(microseconds=1)),
        (7, "after", date + timedelta(days=1)),
        (8, "other", date),
    ]:
        lake.execute(
            f"INSERT INTO {table} (team_id, group_type_index, group_key, _timestamp) VALUES (%s, %s, %s, %s)",
            (team, 0, key, timestamp),
        )
    untouched = [(7, "after"), (7, "before"), (8, "other")] if daily else [(8, "other")]
    for name in ("a", "b"):
        lake.execute(
            f"COPY (SELECT * REPLACE ('{name}' AS group_key) FROM {table} WHERE team_id = 7 AND group_key = 'old') TO %s (FORMAT PARQUET)",
            (str(tmp_path / f"{name}.parquet"),),
        )
    valid_second_file = (tmp_path / "b.parquet").read_bytes()
    if scenario == "invalid_file":
        (tmp_path / "b.parquet").write_bytes(b"invalid parquet")
    config = DucklingBackfillConfig(
        cleanup_existing_partition_data=scenario != "append",
        dry_run=scenario == "dry_run",
        skip_ducklake_registration=scenario == "skip_registration",
    )
    context = MagicMock()
    context.partition_key = "7_2025-12-31" if daily else "7"
    context.run.run_id = "synthetic-run"
    cluster = MagicMock()
    preview = config.dry_run or config.skip_ducklake_registration
    adapter = cast(_LakeConnection, cast(object, lake))
    execute = adapter.execute
    registrations = 0
    failing_export = scenario == "export_failure"

    def export_result(**kwargs: object) -> MagicMock:
        if not preview and config.cleanup_existing_partition_data:
            assert (
                lake.execute(f"SELECT team_id, group_key FROM {table} ORDER BY team_id, group_key").fetchall()
                == untouched
            )
        if failing_export:
            raise RuntimeError("export failed")
        result = MagicMock()
        result.result.return_value = (
            None if config.dry_run else str(tmp_path / ("empty-*.parquet" if scenario == "empty" else "*.parquet"))
        )
        return result

    def execute_with_disconnect(
        query: str | sql.Composable, params: tuple[object, ...] | None = None
    ) -> _LakeConnection:
        nonlocal registrations
        result = execute(query, params)
        if isinstance(query, str) and query.startswith("CALL ducklake_add_data_files"):
            registrations += 1
            if (scenario == "partial_disconnect" and registrations == 1) or (
                scenario == "committed_disconnect" and registrations == 2
            ):
                raise psycopg.OperationalError("server closed the connection unexpectedly")
        return result

    cluster.any_host_by_role.side_effect = export_result
    with (
        patch("products.managed_warehouse.dags.groups_backfill._resolve_duckling_target", return_value=target),
        patch("products.managed_warehouse.dags.groups_backfill.resolve_groups_table", return_value="groups_production"),
        patch("products.managed_warehouse.dags.groups_backfill._get_cluster", return_value=cluster),
        patch("products.managed_warehouse.dags.groups_backfill.record_duckling_backfill_workload"),
        patch("posthog.dags.events_backfill_to_duckling._mint_backfill_service_credential", return_value=None),
        patch("posthog.dags.events_backfill_to_duckling._connect_duckgres", return_value=lake) as connect,
        patch("posthog.dags.events_backfill_to_duckling.time.sleep"),
        patch.object(adapter, "execute", side_effect=execute_with_disconnect),
    ):
        if scenario in ("invalid_file", "export_failure"):
            with pytest.raises(duckdb.Error if scenario == "invalid_file" else RuntimeError):
                run_groups_backfill(context, config)
            expected = sorted(untouched + ([(7, "a")] if scenario == "invalid_file" else []))
            assert (
                lake.execute(f"SELECT team_id, group_key FROM {table} ORDER BY team_id, group_key").fetchall()
                == expected
            )
            (tmp_path / "b.parquet").write_bytes(valid_second_file)
            failing_export = False
        run_groups_backfill(context, config)
        assert bool(connect.call_count) is not preview

    expected_rows = list(untouched)
    if scenario not in ("empty", "dry_run", "skip_registration"):
        expected_rows.extend([(7, "a"), (7, "b")])
    if scenario in ("append", "dry_run", "skip_registration"):
        expected_rows.append((7, "old"))
        if not daily:
            expected_rows.extend([(7, "before"), (7, "after")])
    assert lake.execute(f"SELECT team_id, group_key FROM {table} ORDER BY team_id, group_key").fetchall() == sorted(
        expected_rows
    )
    expected_files = 0 if scenario in ("empty", "dry_run", "skip_registration") else 2
    metadata = context.add_output_metadata.call_args.args[0]
    assert metadata["files_registered"] == expected_files
    assert metadata["export_mode"] == ("daily" if daily else "full")


class _FakeGroupsCatalog:
    def __init__(self) -> None:
        self.tables: list[tuple[str, dict[str, str]]] = []
        self.registered: list[tuple[str, list[str], DuckLakeDayReplacement | DuckLakeTableReplacement | None]] = []

    def ensure_table(
        self, table: str, columns: dict[str, str], *, drop_first: bool, create_if_missing: bool, validate: bool
    ) -> None:
        self.tables.append((table, dict(columns)))

    def register_files(
        self,
        table: str,
        files: list[str],
        *,
        import_id: str,
        replacement: DuckLakeDayReplacement | DuckLakeTableReplacement | None,
    ) -> int:
        self.registered.append((table, list(files), replacement))
        return len(files)


@pytest.mark.parametrize(
    "partition_key,replacement",
    [
        ("7", DuckLakeTableReplacement()),
        ("7_2025-12-31", DuckLakeDayReplacement(column="_timestamp", day=datetime(2025, 12, 31).date())),
    ],
)
@time_machine.travel(datetime(2026, 1, 1, tzinfo=UTC), tick=False)
def test_groups_backfill_registers_through_trino_without_duckgres(
    partition_key: str, replacement: DuckLakeDayReplacement | DuckLakeTableReplacement
) -> None:
    inserts, catalog, connect_catalog, context = _run_groups_through_trino(partition_key, DucklingBackfillConfig())

    connect_catalog.assert_called_once_with("org")
    assert catalog.tables == [("groups_team_7", GROUPS_TRINO_COLUMN_TYPES)]
    [(table, files, registered_replacement)] = catalog.registered
    assert (table, registered_replacement) == ("groups_team_7", replacement)
    [insert] = inserts
    export_path = re.search(r"s3\('([^']+)'", insert)
    assert export_path is not None
    assert files == [
        export_path[1].replace("https://bkt.s3.us-east-1.amazonaws.com/", "s3://bkt/").replace("{_partition_id}", "0")
    ]
    assert "toInt16(group_type_index) AS group_type_index" in insert
    assert "toDateTime64(created_at, 6, 'UTC') AS created_at" in insert
    assert context.add_output_metadata.call_args.args[0]["files_registered"] == 1


@pytest.mark.parametrize("partition_key", ["7", "7_2025-12-31"])
@time_machine.travel(datetime(2026, 1, 1, tzinfo=UTC), tick=False)
def test_groups_export_only_writes_the_trino_types_without_registering(partition_key: str) -> None:
    inserts, catalog, connect_catalog, _ = _run_groups_through_trino(
        partition_key, DucklingBackfillConfig(skip_ducklake_registration=True)
    )

    connect_catalog.assert_not_called()
    assert catalog.registered == []
    [insert] = inserts
    assert "toInt16(group_type_index) AS group_type_index" in insert
    assert "toDateTime64(created_at, 6, 'UTC') AS created_at" in insert


def _run_groups_through_trino(
    partition_key: str, config: DucklingBackfillConfig
) -> tuple[list[str], _FakeGroupsCatalog, MagicMock, MagicMock]:
    target = DucklingTarget(team_id=7, organization_id="org", bucket="bkt", bucket_region="us-east-1")
    inserts: list[str] = []

    def execute(query: str, params: object = None, settings: object = None) -> list[tuple[object, ...]]:
        if "INSERT INTO FUNCTION" in query:
            inserts.append(query)
            return []
        if "'One'" in query:
            return [("0.parquet",)]
        return [(10,)]

    client = MagicMock()
    client.execute.side_effect = execute
    cluster = MagicMock()
    cluster.any_host_by_role.side_effect = lambda fn, **_: MagicMock(result=MagicMock(return_value=fn(client)))
    catalog = _FakeGroupsCatalog()
    context = MagicMock()
    context.partition_key = partition_key
    context.run.run_id = "synthetic-run"
    with (
        patch("products.managed_warehouse.dags.groups_backfill._resolve_duckling_target", return_value=target),
        patch("products.managed_warehouse.dags.groups_backfill.resolve_groups_table", return_value="groups_team_7"),
        patch("products.managed_warehouse.dags.groups_backfill.backfills_through_trino", return_value=True),
        patch("products.managed_warehouse.dags.groups_backfill._DuckgresSession") as duckgres,
        patch("products.managed_warehouse.dags.groups_backfill.record_duckling_backfill_workload"),
        patch("posthog.dags.events_backfill_to_duckling._get_cluster", return_value=cluster),
        patch("posthog.dags.events_backfill_to_duckling.connect_backfill_catalog") as connect_catalog,
    ):
        connect_catalog.return_value.__enter__.return_value = catalog
        run_groups_backfill(context, config)

    duckgres.assert_not_called()
    return inserts, catalog, connect_catalog, context


_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _membership(team_id: int) -> ManagedWarehouseTeamMembership:
    return ManagedWarehouseTeamMembership(
        team_id=team_id,
        organization_id="org",
        schema_name=f"team_{team_id}",
        enabled=True,
        backfill_enabled=True,
        table_names=ManagedWarehouseTableNames(
            events_table="events",
            persons_table="persons",
            groups_table=f"groups_{team_id}",
            data_imports_schema="imports",
        ),
        earliest_event_date=None,
    )


def _add_run(
    instance: DagsterInstance,
    team_id: int,
    run_id: str,
    status: DagsterRunStatus,
    *,
    snapshot: bool = True,
    age_seconds: int = RETRY_BASE_SECONDS + 1,
    partition_key: str | None = None,
) -> None:
    with time_machine.travel(datetime.now(UTC) - timedelta(seconds=age_seconds), tick=False):
        instance.add_run(
            DagsterRun(
                job_name=GROUPS_JOB_NAME,
                run_id=run_id,
                status=status,
                tags={
                    "dagster/partition": partition_key or str(team_id),
                    GROUPS_SNAPSHOT_TAG: "true" if snapshot else "false",
                },
            )
        )
        if status in (DagsterRunStatus.FAILURE, DagsterRunStatus.CANCELED):
            run = instance.get_run_by_id(run_id)
            assert run is not None
            instance.report_run_failed(run)


@pytest.mark.parametrize(
    "status,preview,should_schedule",
    [
        (None, False, True),
        (DagsterRunStatus.FAILURE, False, True),
        (DagsterRunStatus.CANCELED, False, True),
        (DagsterRunStatus.STARTING, False, False),
        (DagsterRunStatus.SUCCESS, False, False),
        (DagsterRunStatus.SUCCESS, True, True),
    ],
)
@time_machine.travel(_NOW, tick=False)
def test_groups_discovery_retries_only_when_no_snapshot_succeeded_or_is_running(
    status: DagsterRunStatus | None, preview: bool, should_schedule: bool
) -> None:
    with DagsterInstance.ephemeral() as instance:
        if status is not None:
            instance.add_dynamic_partitions("duckling_groups_backfill", ["7"])
            _add_run(instance, 7, "prior", status, snapshot=not preview)
        with (
            patch(
                "products.managed_warehouse.dags.groups_backfill.list_enabled_backfill_team_memberships",
                return_value=[_membership(7)],
            ),
            patch("products.managed_warehouse.dags.groups_backfill._repair_stale_running_statuses"),
        ):
            result = duckling_groups_full_backfill_sensor(build_sensor_context(instance=instance))
        assert isinstance(result, SensorResult)
        assert [r.partition_key for r in result.run_requests or []] == (["7"] if should_schedule else [])


@pytest.mark.parametrize("prior_status", [DagsterRunStatus.SUCCESS, DagsterRunStatus.STARTED])
@time_machine.travel(_NOW, tick=False)
def test_preview_after_snapshot_or_during_active_snapshot_does_not_schedule_another_run(
    prior_status: DagsterRunStatus,
) -> None:
    with DagsterInstance.ephemeral() as instance:
        _add_run(instance, 7, "snapshot", prior_status)
        _add_run(instance, 7, "preview", DagsterRunStatus.SUCCESS, snapshot=False)
        with (
            patch(
                "products.managed_warehouse.dags.groups_backfill.list_enabled_backfill_team_memberships",
                return_value=[_membership(7)],
            ),
            patch("products.managed_warehouse.dags.groups_backfill._repair_stale_running_statuses"),
        ):
            result = duckling_groups_full_backfill_sensor(build_sensor_context(instance=instance))
        assert isinstance(result, SensorResult)
        assert not result.run_requests


@pytest.mark.parametrize("daily", [False, True])
@time_machine.travel(_NOW, tick=False)
def test_failed_teams_do_not_starve_discovery_and_storage_reads_are_bounded(daily: bool) -> None:
    memberships = [_membership(i) for i in range(1, MAX_TEAMS_PER_TICK + 10)]
    evaluate = duckling_groups_daily_backfill_sensor if daily else duckling_groups_full_backfill_sensor
    with DagsterInstance.ephemeral() as instance:
        if daily:
            for row in memberships:
                _add_run(instance, row.team_id, f"initial-{row.team_id}", DagsterRunStatus.SUCCESS, age_seconds=86400)
        for team_id in range(1, 4):
            _add_run(
                instance,
                team_id,
                f"failure-{team_id}",
                DagsterRunStatus.FAILURE,
                partition_key=f"{team_id}_2025-12-31" if daily else None,
            )
        with (
            patch(
                "products.managed_warehouse.dags.groups_backfill.list_enabled_backfill_team_memberships",
                return_value=memberships,
            ),
            patch("products.managed_warehouse.dags.groups_backfill._repair_stale_running_statuses"),
        ):
            first = evaluate(build_sensor_context(instance=instance))
            assert isinstance(first, SensorResult)
            second = evaluate(build_sensor_context(instance=instance, cursor=first.cursor))
            assert isinstance(second, SensorResult)
            assert [r.partition_key for r in second.run_requests or []] == [
                f"{team_id}_2025-12-31" if daily else str(team_id) for team_id in (4, 5, 6)
            ]
            for row in memberships:
                _add_run(
                    instance,
                    row.team_id,
                    f"success-{row.team_id}",
                    DagsterRunStatus.SUCCESS,
                    age_seconds=0,
                    partition_key=f"{row.team_id}_2025-12-31" if daily else None,
                )
            with patch.object(instance, "get_run_records", wraps=instance.get_run_records) as reads:
                scanned = evaluate(build_sensor_context(instance=instance))
            assert isinstance(scanned, SensorResult)
            assert scanned.cursor == str(MAX_TEAMS_PER_TICK)
            assert reads.call_count <= MAX_TEAMS_PER_TICK * (2 if daily else 1)
            wrapped = evaluate(build_sensor_context(instance=instance, cursor=str(memberships[-1].team_id)))
            assert isinstance(wrapped, SensorResult)
            assert wrapped.cursor == str(MAX_TEAMS_PER_TICK)


@pytest.mark.parametrize("daily", [False, True])
@pytest.mark.parametrize(
    "failures,age_seconds,expected",
    [
        (1, 0, False),
        (1, RETRY_BASE_SECONDS + 1, True),
        (6, RETRY_BASE_SECONDS + 1, False),
        (6, RETRY_BASE_SECONDS * 32 + 1, True),
    ],
)
@time_machine.travel(_NOW, tick=False)
def test_failed_snapshot_observes_retry_backoff(daily: bool, failures: int, age_seconds: int, expected: bool) -> None:
    evaluate = duckling_groups_daily_backfill_sensor if daily else duckling_groups_full_backfill_sensor
    with DagsterInstance.ephemeral() as instance:
        if daily:
            _add_run(instance, 7, "initial", DagsterRunStatus.SUCCESS, age_seconds=86400)
        for i in range(failures):
            _add_run(
                instance,
                7,
                f"failed-{i}",
                DagsterRunStatus.FAILURE,
                age_seconds=age_seconds,
                partition_key="7_2025-12-31" if daily else None,
            )
        with (
            patch(
                "products.managed_warehouse.dags.groups_backfill.list_enabled_backfill_team_memberships",
                return_value=[_membership(7)],
            ),
            patch("products.managed_warehouse.dags.groups_backfill._repair_stale_running_statuses"),
        ):
            result = evaluate(build_sensor_context(instance=instance))
        assert isinstance(result, SensorResult)
        assert bool(result.run_requests) == expected


@pytest.mark.parametrize(
    "initial_age,status,age_seconds,run_kind,expected",
    [
        (None, None, 0, "daily", False),
        (None, DagsterRunStatus.SUCCESS, 0, "preview", False),
        (None, DagsterRunStatus.FAILURE, RETRY_BASE_SECONDS + 1, "daily", False),
        (86400, None, 0, "daily", True),
        (0, None, 0, "daily", True),
        (86400, DagsterRunStatus.SUCCESS, 0, "preview", True),
        (86400, DagsterRunStatus.STARTED, 0, "daily", False),
        (86400, DagsterRunStatus.STARTED, 0, "full", False),
        (86400, DagsterRunStatus.SUCCESS, 0, "daily", False),
        (86400, DagsterRunStatus.FAILURE, 0, "daily", False),
        (86400, DagsterRunStatus.FAILURE, RETRY_BASE_SECONDS + 1, "daily", True),
        (86400, DagsterRunStatus.CANCELED, RETRY_BASE_SECONDS + 1, "daily", True),
    ],
)
@time_machine.travel(_NOW, tick=False)
def test_daily_groups_topup_requires_initial_full_success_and_observes_its_own_runs(
    initial_age: int | None, status: DagsterRunStatus | None, age_seconds: int, run_kind: str, expected: bool
) -> None:
    with DagsterInstance.ephemeral() as instance:
        if initial_age is not None:
            _add_run(instance, 7, "initial", DagsterRunStatus.SUCCESS, age_seconds=initial_age)
        if status is not None:
            _add_run(
                instance,
                7,
                "latest",
                status,
                age_seconds=age_seconds,
                snapshot=run_kind != "preview",
                partition_key="7" if run_kind == "full" else "7_2025-12-31",
            )
        with (
            patch(
                "products.managed_warehouse.dags.groups_backfill.list_enabled_backfill_team_memberships",
                return_value=[_membership(7)],
            ),
            patch("products.managed_warehouse.dags.groups_backfill._repair_stale_running_statuses"),
        ):
            result = duckling_groups_daily_backfill_sensor(build_sensor_context(instance=instance))
            assert isinstance(result, SensorResult)
            assert bool(result.run_requests) == expected
            if initial_age is not None:
                initial = duckling_groups_full_backfill_sensor(build_sensor_context(instance=instance))
                assert isinstance(initial, SensorResult)
                assert not initial.run_requests


@time_machine.travel(_NOW, tick=False)
def test_daily_groups_topup_is_partitioned_by_yesterday_and_retries_with_a_new_run_key() -> None:
    with (
        DagsterInstance.ephemeral() as instance,
        patch(
            "products.managed_warehouse.dags.groups_backfill.list_enabled_backfill_team_memberships",
            return_value=[_membership(7)],
        ),
        patch("products.managed_warehouse.dags.groups_backfill._repair_stale_running_statuses"),
    ):
        _add_run(instance, 7, "initial", DagsterRunStatus.SUCCESS, age_seconds=86400)

        def requests() -> Sequence[RunRequest]:
            result = duckling_groups_daily_backfill_sensor(build_sensor_context(instance=instance))
            assert isinstance(result, SensorResult)
            return result.run_requests or []

        first = requests()[0]
        assert first.partition_key == "7_2025-12-31"
        result = duckling_groups_daily_backfill_sensor(build_sensor_context(instance=instance))
        assert isinstance(result, SensorResult)
        assert result.dynamic_partitions_requests is not None
        assert result.dynamic_partitions_requests[0].partition_keys == ["7_2025-12-31"]
        assert first.tags[GROUPS_REFRESH_DATE_TAG] == "2025-12-31"
        assert requests()[0].run_key == first.run_key
        _add_run(instance, 7, "failed", DagsterRunStatus.FAILURE, partition_key="7_2025-12-31")
        assert requests()[0].run_key != first.run_key
        _add_run(instance, 7, "refreshed", DagsterRunStatus.SUCCESS, age_seconds=0, partition_key="7_2025-12-31")
        assert not requests()
        with time_machine.travel(_NOW + timedelta(hours=1), tick=False):
            _add_run(instance, 7, "failed-rerun", DagsterRunStatus.FAILURE, partition_key="7_2025-12-31")
            assert requests()[0].run_key not in (first.run_key, "7_2025-12-31_groups_failed")
        with time_machine.travel(_NOW + timedelta(days=1), tick=False):
            tomorrow = requests()[0]
            assert tomorrow.run_key != first.run_key
            assert tomorrow.partition_key == "7_2026-01-01"
            assert tomorrow.tags[GROUPS_REFRESH_DATE_TAG] == "2026-01-01"


@pytest.mark.parametrize("config", [{"dry_run": True}, {"skip_ducklake_registration": True}])
@pytest.mark.parametrize("partition_key", ["7", "7_2025-12-31"])
def test_preview_clears_inherited_snapshot_tag(config: dict[str, bool], partition_key: str) -> None:
    with DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions("duckling_groups_backfill", [partition_key])
        with patch("products.managed_warehouse.dags.groups_backfill.run_groups_backfill"):
            result = materialize(
                [duckling_groups_backfill],
                instance=instance,
                partition_key=partition_key,
                tags={GROUPS_SNAPSHOT_TAG: "true"},
                run_config={"ops": {"duckling_groups_backfill": {"config": config}}},
            )
        assert result.success
        run = instance.get_run_by_id(result.run_id)
        assert run is not None
        assert run.tags[GROUPS_SNAPSHOT_TAG] == "false"


def test_delete_tables_refuses_legacy_shared_table(lake: psycopg.Connection[tuple[object, ...]]) -> None:
    with pytest.raises(ValueError, match="shared groups table"):
        ensure_groups_table(lake, "groups", DucklingBackfillConfig(delete_tables=True))
