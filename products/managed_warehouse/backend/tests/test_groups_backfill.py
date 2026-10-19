from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
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
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)
from products.managed_warehouse.dags.groups_backfill import (
    GROUPS_JOB_NAME,
    GROUPS_SNAPSHOT_TAG,
    MAX_TEAMS_PER_TICK,
    RETRY_BASE_SECONDS,
    duckling_groups_backfill,
    duckling_groups_full_backfill_sensor,
    ensure_groups_table,
    export_groups_to_duckling_s3,
    groups_snapshot_select_sql,
    run_groups_backfill,
)


def test_groups_snapshot_deduplicates_keys_within_each_team_and_group_type(monkeypatch: pytest.MonkeyPatch) -> None:
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
            query = groups_snapshot_select_sql(7).replace("FROM groups FINAL", f"FROM {table_name} FINAL")
            rows = client.execute(query)
        finally:
            client.execute(f"DROP TABLE {table_name}")
    assert sorted(row[:6] for row in rows) == [
        (7, 0, "company", '{"name":"latest"}', created, latest),
        (7, 0, "tied", '{"name":"last insert"}', created, latest),
        (7, 1, "company", '{"name":"another type"}', created, latest),
    ]


@pytest.mark.parametrize("memory_override", [None, 20 * 1024**3])
def test_groups_export_memory_default_and_operator_override(memory_override: int | None) -> None:
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
        result = export_groups_to_duckling_s3(context, client, config, target)

    export_query = client.execute.call_args.args[0]
    export_settings = client.execute.call_args.kwargs["settings"]
    assert result == "s3://unused/backfill/groups/7/synthetic-run/*.parquet"
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
def test_groups_full_backfill_cleans_team_and_replays_registration(
    lake: psycopg.Connection[tuple[object, ...]], tmp_path: Path, scenario: str
) -> None:
    table = f"{DUCKLAKE_ALIAS}.posthog.groups_production"
    target = DucklingTarget(team_id=7, organization_id="org", bucket="unused", bucket_region="us-east-1")
    lake.execute(f"INSERT INTO {table} (team_id, group_type_index, group_key) VALUES (7, 0, 'old'), (8, 0, 'other')")
    for name in ("a", "b"):
        lake.execute(
            f"COPY (SELECT * REPLACE ('{name}' AS group_key) FROM {table} WHERE team_id = 7) TO %s (FORMAT PARQUET)",
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
    context.partition_key = "7"
    context.run.run_id = "synthetic-run"
    cluster = MagicMock()
    preview = config.dry_run or config.skip_ducklake_registration
    adapter = cast(_LakeConnection, cast(object, lake))
    execute = adapter.execute
    registrations = 0
    failing_export = scenario == "export_failure"

    def export_result(**kwargs: object) -> MagicMock:
        if not preview and config.cleanup_existing_partition_data:
            assert lake.execute(f"SELECT group_key FROM {table} WHERE team_id = 7").fetchall() == []
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
            expected = [(7, "a"), (8, "other")] if scenario == "invalid_file" else [(8, "other")]
            assert (
                lake.execute(f"SELECT team_id, group_key FROM {table} ORDER BY team_id, group_key").fetchall()
                == expected
            )
            (tmp_path / "b.parquet").write_bytes(valid_second_file)
            failing_export = False
        run_groups_backfill(context, config)
        assert bool(connect.call_count) is not preview

    expected_rows = [(8, "other")]
    if scenario not in ("empty", "dry_run", "skip_registration"):
        expected_rows.extend([(7, "a"), (7, "b")])
    if scenario in ("append", "dry_run", "skip_registration"):
        expected_rows.append((7, "old"))
    assert lake.execute(f"SELECT team_id, group_key FROM {table} ORDER BY team_id, group_key").fetchall() == sorted(
        expected_rows
    )
    expected_files = 0 if scenario in ("empty", "dry_run", "skip_registration") else 2
    assert context.add_output_metadata.call_args.args[0]["files_registered"] == expected_files


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
) -> None:
    instance.add_run(
        DagsterRun(
            job_name=GROUPS_JOB_NAME,
            run_id=run_id,
            status=status,
            tags={"dagster/partition": str(team_id), GROUPS_SNAPSHOT_TAG: "true" if snapshot else "false"},
        )
    )
    if status in (DagsterRunStatus.FAILURE, DagsterRunStatus.CANCELED):
        run = instance.get_run_by_id(run_id)
        assert run is not None
        with time_machine.travel(_NOW - timedelta(seconds=age_seconds), tick=False):
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


@time_machine.travel(_NOW, tick=False)
def test_failed_teams_do_not_starve_discovery_and_storage_reads_are_bounded() -> None:
    memberships = [_membership(i) for i in range(1, MAX_TEAMS_PER_TICK + 10)]
    with DagsterInstance.ephemeral() as instance:
        for team_id in range(1, 4):
            _add_run(instance, team_id, f"failure-{team_id}", DagsterRunStatus.FAILURE)
        with (
            patch(
                "products.managed_warehouse.dags.groups_backfill.list_enabled_backfill_team_memberships",
                return_value=memberships,
            ),
            patch("products.managed_warehouse.dags.groups_backfill._repair_stale_running_statuses"),
        ):
            first = duckling_groups_full_backfill_sensor(build_sensor_context(instance=instance))
            assert isinstance(first, SensorResult)
            second = duckling_groups_full_backfill_sensor(build_sensor_context(instance=instance, cursor=first.cursor))
            assert isinstance(second, SensorResult)
            assert [r.partition_key for r in second.run_requests or []] == ["4", "5", "6"]
            for row in memberships:
                _add_run(instance, row.team_id, f"success-{row.team_id}", DagsterRunStatus.SUCCESS)
            with patch.object(instance, "get_run_records", wraps=instance.get_run_records) as reads:
                scanned = duckling_groups_full_backfill_sensor(build_sensor_context(instance=instance))
            assert isinstance(scanned, SensorResult)
            assert scanned.cursor == str(MAX_TEAMS_PER_TICK)
            assert reads.call_count <= MAX_TEAMS_PER_TICK
            wrapped = duckling_groups_full_backfill_sensor(
                build_sensor_context(instance=instance, cursor=str(memberships[-1].team_id))
            )
            assert isinstance(wrapped, SensorResult)
            assert wrapped.cursor == str(MAX_TEAMS_PER_TICK)


@pytest.mark.parametrize("age_seconds,expected", [(0, False), (RETRY_BASE_SECONDS + 1, True)])
@time_machine.travel(_NOW, tick=False)
def test_failed_snapshot_observes_retry_backoff(age_seconds: int, expected: bool) -> None:
    with DagsterInstance.ephemeral() as instance:
        _add_run(instance, 7, "failed", DagsterRunStatus.FAILURE, age_seconds=age_seconds)
        with (
            patch(
                "products.managed_warehouse.dags.groups_backfill.list_enabled_backfill_team_memberships",
                return_value=[_membership(7)],
            ),
            patch("products.managed_warehouse.dags.groups_backfill._repair_stale_running_statuses"),
        ):
            result = duckling_groups_full_backfill_sensor(build_sensor_context(instance=instance))
        assert isinstance(result, SensorResult)
        assert bool(result.run_requests) == expected


@pytest.mark.parametrize("config", [{"dry_run": True}, {"skip_ducklake_registration": True}])
def test_preview_clears_inherited_snapshot_tag(config: dict[str, bool]) -> None:
    with DagsterInstance.ephemeral() as instance:
        instance.add_dynamic_partitions("duckling_groups_backfill", ["7"])
        with patch("products.managed_warehouse.dags.groups_backfill.run_groups_backfill"):
            result = materialize(
                [duckling_groups_backfill],
                instance=instance,
                partition_key="7",
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
