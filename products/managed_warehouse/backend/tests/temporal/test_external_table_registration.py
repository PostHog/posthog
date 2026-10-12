from __future__ import annotations

import uuid
import datetime as dt
import threading
import contextlib
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest
from unittest.mock import patch

import duckdb
import fsspec
import pyarrow as pa
import deltalake
import pyarrow.parquet as pq
from psycopg import sql
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from products.managed_warehouse.backend.external_tables import enroll_external_table
from products.managed_warehouse.backend.models import ManagedWarehouseExternalTable
from products.managed_warehouse.backend.temporal import external_table_registration_workflow as registration_module
from products.managed_warehouse.backend.temporal.external_delta_snapshot import (
    PreparedDeltaSnapshot,
    prepare_delta_snapshot,
)
from products.managed_warehouse.backend.temporal.external_table_registration_workflow import (
    ExternalTableRegistrationAttempt,
    PublishedDeltaSnapshot,
    publish_external_snapshot,
    read_published_snapshot,
    register_external_table_activity,
)
from products.managed_warehouse.backend.temporal.parquet_registration import ParquetRegistration
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

if TYPE_CHECKING:
    import s3fs
    import psycopg

    from posthog.models import Team


class LocalDuckgresConnection:
    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self.connection = connection
        self.lose_commit_acknowledgement = False

    def execute(self, query: sql.Composable | str) -> duckdb.DuckDBPyConnection:
        query_text = query.as_string() if isinstance(query, sql.Composable) else query
        return self.connection.execute(query_text.replace("s3://", ""))

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        self.connection.execute("BEGIN")
        try:
            yield
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")
            if self.lose_commit_acknowledgement:
                self.lose_commit_acknowledgement = False
                raise ConnectionError("commit acknowledgement lost")


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[LocalDuckgresConnection]:
    with duckdb.connect(config={"autoinstall_known_extensions": False, "autoload_known_extensions": False}) as raw:
        installed = raw.execute(
            "SELECT installed FROM duckdb_extensions() WHERE extension_name = 'ducklake'"
        ).fetchone()
        if installed is None or not installed[0]:
            pytest.skip("DuckLake integration tests require a preinstalled matching extension")
        raw.execute("LOAD ducklake")
        conn = LocalDuckgresConnection(raw)
        conn.execute(
            sql.SQL("ATTACH {} AS ducklake (DATA_PATH {})").format(
                sql.Literal(f"ducklake:{tmp_path / 'metadata.duckdb'}"),
                sql.Literal(str(tmp_path / "data")),
            )
        )
        raw.execute("USE ducklake")
        yield conn


def prepare_registration(tmp_path: Path, connection: LocalDuckgresConnection, value: int) -> ParquetRegistration:
    folder = tmp_path / uuid.uuid4().hex
    folder.mkdir()
    path = folder / "part.parquet"
    pq.write_table(pa.table({"id": [value]}), path)
    registration = ParquetRegistration(
        schema_name="imports",
        table_name="external_orders",
        shadow_name=f"__ph_register_{uuid.uuid4().hex}",
        previous_name=f"__ph_previous_{uuid.uuid4().hex}",
        parquet_glob=str(folder / "*.parquet"),
    )
    typed_connection = cast("psycopg.Connection", connection)
    registration.prepare(typed_connection, [[str(path)]], ())
    assert registration.verify(typed_connection) == 1
    return registration


def marker(version: int) -> PublishedDeltaSnapshot:
    return PublishedDeltaSnapshot(
        table_id="00000000-0000-0000-0000-000000000001",
        fingerprint="source-fingerprint",
        delta_table_id="delta-table-id",
        version=version,
    )


@pytest.mark.parametrize("candidate_version", [3, 4, 5])
def test_publication_never_replaces_a_newer_or_equal_snapshot(
    tmp_path: Path, connection: LocalDuckgresConnection, candidate_version: int
) -> None:
    first = prepare_registration(tmp_path, connection, 4)
    publish_external_snapshot(cast("psycopg.Connection", connection), first, marker(4))
    candidate = prepare_registration(tmp_path, connection, candidate_version)
    published = publish_external_snapshot(cast("psycopg.Connection", connection), candidate, marker(candidate_version))
    assert published.version == max(4, candidate_version)
    assert connection.connection.execute("SELECT id FROM imports.external_orders").fetchall() == [
        (max(4, candidate_version),)
    ]


def test_commit_acknowledgement_loss_keeps_a_recoverable_publication(
    tmp_path: Path, connection: LocalDuckgresConnection
) -> None:
    registration = prepare_registration(tmp_path, connection, 9)
    connection.lose_commit_acknowledgement = True
    with pytest.raises(ConnectionError):
        publish_external_snapshot(cast("psycopg.Connection", connection), registration, marker(9))
    assert read_published_snapshot(cast("psycopg.Connection", connection), registration) == marker(9)
    assert connection.connection.execute("SELECT id FROM imports.external_orders").fetchall() == [(9,)]


@pytest.mark.parametrize(
    "changed",
    [
        replace(marker(2), table_id="different"),
        replace(marker(2), fingerprint="different"),
        replace(marker(2), delta_table_id="different"),
    ],
    ids=["table", "configuration", "delta_identity"],
)
def test_changed_source_identity_preserves_the_published_table(
    tmp_path: Path, connection: LocalDuckgresConnection, changed: PublishedDeltaSnapshot
) -> None:
    registration = prepare_registration(tmp_path, connection, 1)
    publish_external_snapshot(cast("psycopg.Connection", connection), registration, marker(1))
    candidate = prepare_registration(tmp_path, connection, 2)
    with pytest.raises(ApplicationError, match="identity changed"):
        publish_external_snapshot(cast("psycopg.Connection", connection), candidate, changed)
    assert connection.connection.execute("SELECT id FROM imports.external_orders").fetchall() == [(1,)]


@pytest.mark.parametrize("empty", [False, True])
def test_snapshot_reads_a_pinned_delta_version_and_excludes_deleted_rows(tmp_path: Path, empty: bool) -> None:
    source = tmp_path / "source"
    original = pa.table({"id": [1, 2], "label": ["first", "second"]})
    deltalake.write_deltalake(source, original)
    current = deltalake.DeltaTable(source)
    current.delete("id = 1" if not empty else "id > 0")
    pinned = deltalake.DeltaTable(source, version=1)
    deltalake.write_deltalake(source, pa.table({"id": [3], "label": ["third"]}), mode="append")
    snapshot = prepare_delta_snapshot(
        pinned, cast("s3fs.S3FileSystem", fsspec.filesystem("file", auto_mkdir=True)), f"s3://{tmp_path / 'snapshot'}"
    )
    assert snapshot.version == 1
    assert snapshot.row_count == (0 if empty else 1)
    output = pa.concat_tables([pq.read_table(path.removeprefix("s3://")) for path in snapshot.paths])
    assert output.to_pydict() == ({"id": [], "label": []} if empty else {"id": [2], "label": ["second"]})
    assert output.schema == original.schema


@pytest.mark.django_db
def test_activity_recovers_the_published_version_after_a_lost_commit_response(
    tmp_path: Path, connection: LocalDuckgresConnection, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "delta"
    deltalake.write_deltalake(source, pa.table({"id": [1, 2]}))
    delta_constructor = deltalake.DeltaTable
    table = DataWarehouseTable.objects.create(
        team=team, name="external_orders", format="Delta", url_pattern="s3://example-bucket/orders"
    )
    with patch(
        "products.managed_warehouse.backend.external_tables.duckgres_data_imports_schema", return_value="imports"
    ):
        enrolled = enroll_external_table(team.id, table.id)
    monkeypatch.setattr(registration_module, "is_dev_mode", lambda: True)
    monkeypatch.setattr(registration_module, "external_table_sync_feature_enabled", lambda _team_id: True)
    monkeypatch.setattr(registration_module, "get_config", lambda: {"DUCKLAKE_BUCKET": str(tmp_path)})
    monkeypatch.setattr(registration_module, "setup_duckgres_session", lambda *args, **kwargs: None)
    monkeypatch.setattr(registration_module, "get_s3_client", lambda: fsspec.filesystem("file", auto_mkdir=True))
    monkeypatch.setattr(
        registration_module, "_connect_to_duckgres_for_team", lambda *args: contextlib.nullcontext(connection)
    )
    monkeypatch.setattr(deltalake, "DeltaTable", lambda *args, **kwargs: delta_constructor(source))
    environment = ActivityEnvironment()
    environment.info = replace(environment.info, start_to_close_timeout=dt.timedelta(hours=4))
    attempt = ExternalTableRegistrationAttempt(team_id=team.id, table_id=table.id, attempt_token=uuid.uuid4().hex)
    assert environment.run(register_external_table_activity, attempt)
    enrolled.refresh_from_db()
    assert enrolled.published_version == 0
    delta_constructor(source).delete("id = 1")
    connection.lose_commit_acknowledgement = True
    with pytest.raises(ApplicationError, match="ConnectionError"):
        environment.run(register_external_table_activity, replace(attempt, attempt_token=uuid.uuid4().hex))
    enrolled.refresh_from_db()
    assert enrolled.published_version == 0
    assert not environment.run(register_external_table_activity, replace(attempt, attempt_token=uuid.uuid4().hex))
    enrolled.refresh_from_db()
    assert enrolled.published_version == 1
    assert enrolled.latest_error is None
    assert connection.connection.execute(
        sql.SQL("SELECT id FROM {}.{}")
        .format(sql.Identifier(enrolled.warehouse_schema), sql.Identifier(enrolled.warehouse_table))
        .as_string()
    ).fetchall() == [(2,)]
    assert ManagedWarehouseExternalTable.objects.for_team(team.id).count() == 1
    deltalake.write_deltalake(source, pa.table({"id": [3]}), mode="append")
    prepare = registration_module.prepare_delta_snapshot

    def disable_during_copy(
        table: deltalake.DeltaTable,
        destination: s3fs.S3FileSystem,
        landing_uri: str,
        cancel_requested: threading.Event | None = None,
    ) -> PreparedDeltaSnapshot:
        snapshot = prepare(table, destination, landing_uri, cancel_requested)
        ManagedWarehouseExternalTable.objects.for_team(team.id).filter(id=enrolled.id).update(enabled=False)
        return snapshot

    monkeypatch.setattr(registration_module, "prepare_delta_snapshot", disable_during_copy)
    assert not environment.run(register_external_table_activity, replace(attempt, attempt_token=uuid.uuid4().hex))
    enrolled.refresh_from_db()
    assert enrolled.published_version == 1
    assert connection.connection.execute(
        sql.SQL("SELECT id FROM {}.{}")
        .format(sql.Identifier(enrolled.warehouse_schema), sql.Identifier(enrolled.warehouse_table))
        .as_string()
    ).fetchall() == [(2,)]
