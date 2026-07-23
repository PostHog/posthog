import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from django.db import connection as django_connection

import psycopg
import structlog

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.database_stats import (
    SNAPSHOT_COLUMNS,
    stats_table_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postgres import (
    PostgresDatabaseStatsConfig,
    PostgresSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import PostgresDiscoveredSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.stats import (
    POSTGRES_STATS_CATALOGS,
    _collect_statements,
    fetch_postgres_stats_columns,
    postgres_database_stats_source,
)

logger = structlog.get_logger()

_SNAPSHOT_COLUMN_NAMES = {name for name, _, _ in SNAPSHOT_COLUMNS}


def _snapshot_base() -> tuple[datetime, str]:
    """The (collected_at, snapshot_id) pair the harness normally stamps a snapshot with."""
    return datetime.now(UTC), uuid.uuid4().hex


@pytest.fixture
def autocommit_pg_connection():
    # Raw autocommit connection to the test DB — the same way the collectors connect in
    # production (each catalog read is its own transaction).
    sd = django_connection.settings_dict
    conn = psycopg.connect(
        host=sd["HOST"] or None,
        port=sd["PORT"] or None,
        dbname=sd["NAME"],
        user=sd["USER"] or None,
        password=sd["PASSWORD"] or None,
        autocommit=True,
    )
    try:
        yield conn
    finally:
        conn.close()


class TestPostgresStatsCatalogs:
    def test_every_catalog_is_keyed_by_its_table_name(self):
        for table_name, catalog in POSTGRES_STATS_CATALOGS.items():
            assert catalog.table_name == table_name
            assert catalog.catalog_relation or catalog.static_columns, table_name

    @pytest.mark.django_db
    def test_columns_come_from_the_server(self, autocommit_pg_connection):
        columns = fetch_postgres_stats_columns(autocommit_pg_connection)

        # Mirrored catalogs report their real columns; a catalog this server doesn't
        # expose (pg_stat_statements without the extension) is simply absent.
        assert {name for name, _, _ in columns["pg_stat_user_tables"]} >= {
            "relid",
            "schemaname",
            "relname",
            "seq_scan",
            "n_dead_tup",
            "last_autovacuum",
        }
        with autocommit_pg_connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_extension WHERE extname = 'pg_stat_statements'")
            installed = cur.fetchone()[0] > 0
        assert ("pg_stat_statements" in columns) is installed


class TestPostgresStatsCollectors:
    """Runs the collectors against the Django test database — a real Postgres with real
    statistics catalogs."""

    def _expected_columns(self, table_name: str, server_columns: dict) -> set[str]:
        catalog = POSTGRES_STATS_CATALOGS[table_name]
        declared = list(catalog.static_columns) or server_columns[table_name]
        return (
            _SNAPSHOT_COLUMN_NAMES
            | {name for name, _, _ in declared}
            | {name for name, _, _ in catalog.computed_columns}
        )

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "table_name",
        [
            "pg_stat_user_tables",
            "pg_stat_user_indexes",
            "pg_statio_user_tables",
            "pg_stat_database",
            "pg_settings",
            "pg_stat_activity_summary",
        ],
    )
    def test_snapshot_keeps_the_catalog_columns_verbatim(self, autocommit_pg_connection, table_name):
        # The point of collecting raw: what lands is the catalog's own columns plus the
        # snapshot identity and any computed extras — nothing renamed, nothing dropped.
        server_columns = fetch_postgres_stats_columns(autocommit_pg_connection)
        collector = POSTGRES_STATS_CATALOGS[table_name].collector

        rows = collector(autocommit_pg_connection, logger, *_snapshot_base())

        assert rows, f"expected rows for {table_name} in the test database"
        assert set(rows[0].keys()) == self._expected_columns(table_name, server_columns)

    @pytest.mark.django_db
    def test_snapshot_identity_is_shared_across_rows(self, autocommit_pg_connection):
        collected_at, snapshot_id = _snapshot_base()
        rows = POSTGRES_STATS_CATALOGS["pg_stat_user_tables"].collector(
            autocommit_pg_connection, logger, collected_at, snapshot_id
        )
        assert {r["snapshot_id"] for r in rows} == {snapshot_id}
        assert {r["collected_at"] for r in rows} == {collected_at}

    @pytest.mark.django_db
    def test_replication_slots_snapshot_is_scoped_and_lag_aware(self, autocommit_pg_connection):
        # No slots on the test database, but the query must still run — it carries the
        # standby check and the current-database filter.
        rows = POSTGRES_STATS_CATALOGS["pg_replication_slots"].collector(
            autocommit_pg_connection, logger, *_snapshot_base()
        )
        assert rows == []

    @pytest.mark.django_db
    def test_statements_snapshot_degrades_without_extension(self, autocommit_pg_connection):
        rows = _collect_statements(autocommit_pg_connection, logger, *_snapshot_base())
        with autocommit_pg_connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_extension WHERE extname = 'pg_stat_statements'")
            installed = cur.fetchone()[0] > 0
        if installed:
            assert rows and _SNAPSHOT_COLUMN_NAMES <= set(rows[0].keys())
        else:
            assert rows == []

    @pytest.mark.django_db
    @pytest.mark.parametrize("table_name", ["pg_stat_user_tables", "pg_stat_user_indexes", "pg_statio_user_tables"])
    def test_schema_scoped_snapshots_cover_only_that_schema(self, autocommit_pg_connection, table_name):
        collector = POSTGRES_STATS_CATALOGS[table_name].collector

        assert collector(autocommit_pg_connection, logger, *_snapshot_base(), source_schema="public")
        assert collector(autocommit_pg_connection, logger, *_snapshot_base(), source_schema="not_a_schema") == []

    @pytest.mark.django_db
    def test_blank_schema_is_treated_as_unscoped(self):
        # `config.schema` is optional and normalizes like discovery does: blank means
        # "every user schema", so the snapshot must not collapse to nothing.
        sd = django_connection.settings_dict
        response = postgres_database_stats_source(
            tunnel=lambda: _fake_tunnel_to(sd),
            user=sd["USER"] or "",
            password=sd["PASSWORD"] or "",
            database=sd["NAME"],
            schema_name=stats_table_name("pg_stat_user_tables"),
            require_ssl=False,
            logger=logger,
            source_schema="   ",
        )
        assert list(cast(Iterable[Any], response.items())) != []


class _ScriptedColumn:
    def __init__(self, name: str):
        self.name = name


class _ScriptedCursor:
    """Minimal psycopg cursor stand-in: routes execute() by SQL substring.

    Drives the statement-collector paths the CI database can't produce — an installed
    pg_stat_statements, on modern or legacy column names — without a network connection.
    """

    def __init__(self, script: list[tuple[str, Any]], executed: list[str] | None = None):
        self._script = script
        self._executed = executed if executed is not None else []
        self._rows: list[tuple] = []
        self.description: list[_ScriptedColumn] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        text = query.as_string(None) if hasattr(query, "as_string") else str(query)
        self._executed.append(text)
        for fragment, outcome in self._script:
            if fragment in text:
                if isinstance(outcome, Exception):
                    raise outcome
                columns, rows = outcome
                self.description = [_ScriptedColumn(name) for name in columns]
                self._rows = list(rows)
                return
        raise AssertionError(f"unexpected query in scripted cursor: {text}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _ScriptedConnection:
    def __init__(self, script: list[tuple[str, Any]]):
        self._script = script
        self.executed: list[str] = []

    def cursor(self):
        return _ScriptedCursor(self._script, self.executed)


class TestCollectStatementsScripted:
    _EXTENSION = ("FROM pg_extension e", (["nspname"], [("public",)]))
    _MODERN_ROWS = (
        ["userid", "dbid", "queryid", "query", "calls", "total_exec_time", "wal_bytes"],
        [(10, 5, 123, "SELECT * FROM users WHERE id = $1", 10, 250.0, 4096)],
    )

    def test_every_catalog_column_survives(self):
        conn = _ScriptedConnection([self._EXTENSION, ("total_exec_time", self._MODERN_ROWS)])
        rows = _collect_statements(cast(Any, conn), logger, *_snapshot_base())

        # Columns this collector used to drop on the floor (wal_bytes, userid, dbid) now
        # land untouched — that's the whole point of snapshotting the catalog as-is.
        assert set(rows[0].keys()) == _SNAPSHOT_COLUMN_NAMES | set(self._MODERN_ROWS[0])
        assert rows[0]["wal_bytes"] == 4096
        assert rows[0]["query"] == "SELECT * FROM users WHERE id = $1"

    def test_legacy_column_names_fall_back(self):
        legacy = (["queryid", "query", "calls", "total_time"], [(789, "SELECT 1", 1, 5.0)])
        conn = _ScriptedConnection(
            [
                self._EXTENSION,
                ('ORDER BY "total_exec_time"', psycopg.errors.UndefinedColumn("no such column")),
                ('ORDER BY "total_time"', legacy),
            ]
        )
        rows = _collect_statements(cast(Any, conn), logger, *_snapshot_base())
        assert rows[0]["total_time"] == 5.0

    def test_unexpected_column_set_skips_the_catalog(self):
        conn = _ScriptedConnection(
            [
                self._EXTENSION,
                ('ORDER BY "total_exec_time"', psycopg.errors.UndefinedColumn("no such column")),
                ('ORDER BY "total_time"', psycopg.errors.UndefinedColumn("still no such column")),
            ]
        )
        assert _collect_statements(cast(Any, conn), logger, *_snapshot_base()) == []

    def test_statements_are_scoped_to_the_connected_database(self):
        # pg_stat_statements is cluster-wide; without the dbid filter another database's
        # query text would land in this team's warehouse table.
        conn = _ScriptedConnection([self._EXTENSION, ("total_exec_time", self._MODERN_ROWS)])
        _collect_statements(cast(Any, conn), logger, *_snapshot_base(), source_schema="analytics")

        statements_query = next(q for q in conn.executed if "pg_stat_statements" in q and "ORDER BY" in q)
        assert "dbid = (SELECT oid FROM pg_database WHERE datname = current_database())" in statements_query
        # ...and no schema filter: pg_stat_statements records no schema, so filtering
        # would empty the table rather than scope it.
        assert "schemaname" not in statements_query


def _stats_config(enabled: bool | None) -> PostgresSourceConfig:
    return PostgresSourceConfig(
        host="localhost",
        database="db",
        user="user",
        password="password",
        port=5432,
        database_stats=None if enabled is None else PostgresDatabaseStatsConfig(enabled=enabled),
    )


@contextmanager
def _fake_tunnel(*args, **kwargs):
    yield ("localhost", 5432)


@contextmanager
def _fake_tunnel_to(settings_dict):
    yield (settings_dict["HOST"] or "localhost", int(settings_dict["PORT"] or 5432))


class TestGetSchemasInjection:
    DISCOVERED = {
        "users": PostgresDiscoveredSchema(
            source_catalog=None,
            source_schema="public",
            source_table_name="users",
            columns=[("id", "integer", False), ("updated_at", "timestamp with time zone", True)],
        )
    }
    _STATS_COLUMNS = {name: [("some_column", "bigint", True)] for name in POSTGRES_STATS_CATALOGS}

    @contextmanager
    def _patched_discovery(self, discovered: dict[str, PostgresDiscoveredSchema]):
        base = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source"
        with (
            patch(f"{base}.get_postgres_schemas", return_value=discovered),
            patch(f"{base}.get_postgres_foreign_keys", return_value={}),
            patch(f"{base}.fetch_postgres_stats_columns", return_value=self._STATS_COLUMNS),
            # The PK/index/RLS/xmin metadata connection is best-effort; a real connection
            # isn't available here, so exercise the degradation path.
            patch(f"{base}.pg_connection", side_effect=Exception("no metadata connection")),
            patch.object(PostgresSource, "with_ssh_tunnel", side_effect=_fake_tunnel),
        ):
            yield

    @pytest.mark.django_db
    def test_stats_tables_are_appended_with_the_server_s_own_columns(self):
        # Real connection to the test database: the declared columns must be the ones
        # this server reports, not a hardcoded list.
        sd = django_connection.settings_dict
        config = PostgresSourceConfig(
            host=sd["HOST"] or "localhost",
            database=sd["NAME"],
            user=sd["USER"] or "",
            password=sd["PASSWORD"] or "",
            port=int(sd["PORT"] or 5432),
            database_stats=PostgresDatabaseStatsConfig(enabled=True),
        )
        base = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source"
        with (
            patch(f"{base}.get_postgres_schemas", return_value=self.DISCOVERED),
            patch(f"{base}.get_postgres_foreign_keys", return_value={}),
            patch.object(
                PostgresSource,
                "with_ssh_tunnel",
                side_effect=lambda *a, **kw: _fake_tunnel_to(sd),
            ),
        ):
            schemas = PostgresSource().get_schemas(config, team_id=1)

        by_name = {s.name: s for s in schemas}
        assert "users" in by_name
        assert stats_table_name("pg_stat_user_tables") in by_name

        declared = [c[0] for c in by_name[stats_table_name("pg_stat_user_tables")].columns]
        assert declared[:2] == ["collected_at", "snapshot_id"]
        assert {"relname", "seq_scan", "n_dead_tup"} <= set(declared)
        assert declared[-1] == "total_size_bytes"

    def test_stats_tables_absent_when_metadata_connection_fails(self):
        # Statistics columns are read on the same connection as the PK/index metadata, so
        # when that connection dies there are no columns to declare and the statistics
        # tables are left out rather than declared empty.
        with self._patched_discovery(self.DISCOVERED):
            schemas = PostgresSource().get_schemas(_stats_config(enabled=True), team_id=1)
        assert [s.name for s in schemas] == ["users"]

    @pytest.mark.parametrize("enabled", [False, None])
    def test_stats_tables_absent_when_disabled(self, enabled):
        with self._patched_discovery(self.DISCOVERED):
            schemas = PostgresSource().get_schemas(_stats_config(enabled=enabled), team_id=1)
        assert [s.name for s in schemas] == ["users"]


class TestStatsSourceRouting:
    def _source(self, team, *, job_inputs=None, pre_ssl_cutoff=False) -> ExternalDataSource:
        source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=team,
            status="running",
            source_type="Postgres",
            job_inputs=job_inputs or {},
        )
        if pre_ssl_cutoff:
            # Pre-SSL-cutoff creation date so the test can reach the local (non-SSL)
            # test database.
            ExternalDataSource.objects.filter(id=source.id).update(created_at="2023-01-01T00:00:00Z")
            source.refresh_from_db()
        return source

    def _inputs(self, team, source, schema_row) -> SourceInputs:
        return SourceInputs(
            schema_name=schema_row.name,
            schema_id=str(schema_row.id),
            source_id=str(source.id),
            team_id=team.pk,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            incremental_field=None,
            incremental_field_type=None,
            job_id=str(uuid.uuid4()),
            logger=logger,
            reset_pipeline=False,
        )

    @pytest.mark.django_db
    def test_source_for_pipeline_routes_a_stats_table_to_its_collector(self, team):
        sd = django_connection.settings_dict
        source = self._source(team, pre_ssl_cutoff=True)
        schema_row = ExternalDataSchema.objects.create(
            name=stats_table_name("pg_stat_user_tables"),
            team_id=team.pk,
            source_id=source.pk,
            sync_type="append",
            sync_type_config={"incremental_field": "collected_at", "incremental_field_type": "DateTime"},
        )
        config = PostgresSourceConfig(
            host=sd["HOST"] or "localhost",
            database=sd["NAME"],
            user=sd["USER"] or "",
            password=sd["PASSWORD"] or "",
            port=int(sd["PORT"] or 5432),
            database_stats=PostgresDatabaseStatsConfig(enabled=True),
        )

        response = PostgresSource().source_for_pipeline(config, self._inputs(team, source, schema_row))

        # Storage name, normalized the same way any qualified table's is (dots become
        # underscores) so HogQL reads from where the pipeline wrote.
        assert response.name == NamingConvention.normalize_identifier(stats_table_name("pg_stat_user_tables"))
        rows = list(cast(Iterable[Any], response.items()))
        assert rows, "expected table statistics from the test database"
        assert {"relname", "seq_scan", "total_size_bytes"} <= set(rows[0].keys())

    @pytest.mark.django_db
    def test_colliding_real_table_syncs_as_a_table_despite_toggle(self, team):
        # A user's own table in a schema called `system_tables` must keep the normal
        # table-sync path. Its row carries source_table_name in the reconciled
        # schema_metadata; injected statistics rows never do.
        source = self._source(team)
        schema_row = ExternalDataSchema.objects.create(
            name=stats_table_name("pg_settings"),
            team_id=team.pk,
            source_id=source.pk,
            sync_type="full_refresh",
            sync_type_config={
                "schema_metadata": {"source_schema": "system_tables", "source_table_name": "pg_settings"}
            },
        )
        config = PostgresSourceConfig(
            host="localhost",
            database="db",
            user="user",
            password="password",
            port=5432,
            database_stats=PostgresDatabaseStatsConfig(enabled=True),
        )
        base = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source"
        with (
            patch(f"{base}.postgres_source", return_value=MagicMock(name="table_response")) as table_source,
            patch(f"{base}.postgres_database_stats_source") as stats_source,
        ):
            PostgresSource().source_for_pipeline(config, self._inputs(team, source, schema_row))

        table_source.assert_called_once()
        stats_source.assert_not_called()
