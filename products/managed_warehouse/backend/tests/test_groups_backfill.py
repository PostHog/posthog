from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest
from unittest.mock import patch

from django.conf import settings

import duckdb
import psycopg
from dagster import DagsterInstance, DagsterRun, DagsterRunStatus, SensorResult, build_sensor_context
from psycopg import sql

from posthog.clickhouse.client.connection import get_client_from_pool
from posthog.dags.events_backfill_to_duckling import DUCKLAKE_ALIAS, DucklingBackfillConfig, DucklingTarget

from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)
from products.managed_warehouse.dags.groups_backfill import (
    GROUPS_JOB_NAME,
    duckling_groups_full_backfill_sensor,
    ensure_groups_table,
    groups_snapshot_select_sql,
    replace_groups_snapshot,
)


def test_groups_snapshot_deduplicates_keys_within_each_team_and_group_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CLICKHOUSE_USE_HTTP", False)
    with get_client_from_pool() as client:
        client.execute("""
            CREATE TEMPORARY TABLE groups (
                team_id Int64, group_type_index UInt8, group_key String, group_properties String,
                created_at DateTime64(6), _timestamp DateTime64(6), _offset UInt64
            ) ENGINE = Memory
        """)
        try:
            created = datetime(2025, 1, 1)
            latest = datetime(2025, 1, 2)
            client.execute(
                "INSERT INTO groups VALUES",
                [
                    (7, 0, "company", '{"name":"old"}', created, created, 1),
                    (7, 0, "company", '{"name":"latest"}', created, latest, 2),
                    (7, 0, "company", '{"name":"latest"}', created, latest, 2),
                    (7, 1, "company", '{"name":"another type"}', created, latest, 2),
                    (8, 0, "company", '{"name":"another team"}', created, latest, 2),
                ],
            )
            rows = client.execute(groups_snapshot_select_sql(7))
        finally:
            client.execute("DROP TEMPORARY TABLE groups")
    assert sorted(row[:6] for row in rows) == [
        (7, 0, "company", '{"name":"latest"}', created, latest),
        (7, 1, "company", '{"name":"another type"}', created, latest),
    ]


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

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.connection.execute("BEGIN")
        try:
            yield
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")


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


@pytest.mark.parametrize("invalid_file", [False, True])
def test_groups_snapshot_replacement_is_replayable_and_rolls_back_failed_registration(
    lake: psycopg.Connection[tuple[object, ...]], tmp_path: Path, invalid_file: bool
) -> None:
    table = f"{DUCKLAKE_ALIAS}.posthog.groups_production"
    target = DucklingTarget(team_id=7, organization_id="org", bucket="unused", bucket_region="us-east-1")
    lake.execute(f"INSERT INTO {table} (team_id, group_type_index, group_key) VALUES (7, 0, 'old'), (8, 0, 'other')")
    lake.execute(
        f"COPY (SELECT * REPLACE ('new' AS group_key) FROM {table} WHERE team_id = 7) TO %s (FORMAT PARQUET)",
        (str(tmp_path / "a.parquet"),),
    )
    if invalid_file:
        (tmp_path / "b.parquet").write_bytes(b"invalid parquet")
        with pytest.raises(duckdb.Error):
            replace_groups_snapshot(lake, target, "groups_production", str(tmp_path / "*.parquet"))
        assert lake.execute(f"SELECT team_id, group_key FROM {table} ORDER BY team_id").fetchall() == [
            (7, "old"),
            (8, "other"),
        ]
    else:
        for _ in range(2):
            assert replace_groups_snapshot(lake, target, "groups_production", str(tmp_path / "*.parquet")) == 1
            assert lake.execute(f"SELECT team_id, group_key FROM {table} ORDER BY team_id").fetchall() == [
                (7, "new"),
                (8, "other"),
            ]
        assert replace_groups_snapshot(lake, target, "groups_production", str(tmp_path / "empty-*.parquet")) == 0
        assert lake.execute(f"SELECT team_id, group_key FROM {table}").fetchall() == [(8, "other")]


@pytest.mark.parametrize(
    "status,config,should_schedule",
    [
        (None, {}, True),
        (DagsterRunStatus.FAILURE, {}, True),
        (DagsterRunStatus.CANCELED, {}, True),
        (DagsterRunStatus.STARTING, {}, False),
        (DagsterRunStatus.SUCCESS, {}, False),
        (DagsterRunStatus.SUCCESS, {"dry_run": True}, True),
        (DagsterRunStatus.SUCCESS, {"skip_ducklake_registration": True}, True),
    ],
)
def test_groups_discovery_retries_only_when_no_snapshot_succeeded_or_is_running(
    status: DagsterRunStatus | None, config: dict[str, bool], should_schedule: bool
) -> None:
    membership = ManagedWarehouseTeamMembership(
        team_id=7,
        organization_id="org",
        schema_name="production",
        enabled=True,
        backfill_enabled=True,
        table_names=ManagedWarehouseTableNames(
            events_table="events_production",
            persons_table="persons_production",
            groups_table="groups_production",
            data_imports_schema="imports_production",
        ),
        earliest_event_date=None,
    )
    with DagsterInstance.ephemeral() as instance:
        if status is not None:
            instance.add_dynamic_partitions("duckling_groups_backfill", ["7"])
            instance.add_run(
                DagsterRun(
                    job_name=GROUPS_JOB_NAME,
                    run_id="prior",
                    status=status,
                    tags={"dagster/partition": "7"},
                    run_config={"ops": {"duckling_groups_backfill": {"config": config}}},
                )
            )
        with (
            patch(
                "products.managed_warehouse.dags.groups_backfill.list_enabled_backfill_team_memberships",
                return_value=[membership],
            ),
            patch("products.managed_warehouse.dags.groups_backfill._repair_stale_running_statuses"),
        ):
            result = duckling_groups_full_backfill_sensor(build_sensor_context(instance=instance))
        assert isinstance(result, SensorResult)
        assert [request.partition_key for request in result.run_requests or []] == (["7"] if should_schedule else [])
