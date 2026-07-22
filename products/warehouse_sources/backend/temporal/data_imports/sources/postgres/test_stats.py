import uuid
from collections.abc import Iterable
from contextlib import contextmanager
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from django.db import connection as django_connection

import psycopg
import structlog

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.database_stats import (
    DATABASE_STATS_COLUMNS,
    DATABASE_STATS_INDEXES,
    DATABASE_STATS_QUERIES,
    DATABASE_STATS_SCHEMA_NAMES,
    DATABASE_STATS_SERVER,
    DATABASE_STATS_TABLES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postgres import (
    PostgresDatabaseStatsConfig,
    PostgresSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import PostgresDiscoveredSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.stats import (
    _collect_indexes,
    _collect_queries,
    _collect_server,
    _collect_tables,
    postgres_database_stats_source,
)

logger = structlog.get_logger()


def _column_names(schema_name: str) -> set[str]:
    return {name for name, _, _ in DATABASE_STATS_COLUMNS[schema_name]}


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


class TestGetSchemasInjection:
    DISCOVERED = {
        "users": PostgresDiscoveredSchema(
            source_catalog=None,
            source_schema="public",
            source_table_name="users",
            columns=[("id", "integer", False), ("updated_at", "timestamp with time zone", True)],
        )
    }

    @contextmanager
    def _patched_discovery(self, discovered: dict[str, PostgresDiscoveredSchema]):
        base = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source"
        with (
            patch(f"{base}.get_postgres_schemas", return_value=discovered),
            patch(f"{base}.get_postgres_foreign_keys", return_value={}),
            # The PK/index/RLS/xmin metadata connection is best-effort: raising here exercises
            # the degradation path and keeps the test off the network.
            patch(f"{base}.pg_connection", side_effect=Exception("no metadata connection")),
            patch.object(PostgresSource, "with_ssh_tunnel", side_effect=_fake_tunnel),
        ):
            yield

    def test_stats_schemas_appended_when_enabled(self):
        with self._patched_discovery(self.DISCOVERED):
            schemas = PostgresSource().get_schemas(_stats_config(enabled=True), team_id=1)
        names = [s.name for s in schemas]
        assert names == ["users", *DATABASE_STATS_SCHEMA_NAMES]

    @pytest.mark.parametrize("enabled", [False, None])
    def test_stats_schemas_absent_when_disabled(self, enabled):
        with self._patched_discovery(self.DISCOVERED):
            schemas = PostgresSource().get_schemas(_stats_config(enabled=enabled), team_id=1)
        assert [s.name for s in schemas] == ["users"]

    def test_names_filter_applies_to_stats_schemas(self):
        with self._patched_discovery(self.DISCOVERED):
            schemas = PostgresSource().get_schemas(
                _stats_config(enabled=True), team_id=1, names=["users", DATABASE_STATS_SERVER]
            )
        assert [s.name for s in schemas] == ["users", DATABASE_STATS_SERVER]

    def test_discovered_table_collision_drops_stats_schema(self):
        discovered = {
            **self.DISCOVERED,
            "public.database_stats_queries": PostgresDiscoveredSchema(
                source_catalog=None,
                source_schema="public",
                source_table_name="database_stats_queries",
                columns=[("id", "integer", False)],
            ),
        }
        with self._patched_discovery(discovered):
            schemas = PostgresSource().get_schemas(_stats_config(enabled=True), team_id=1)
        names = [s.name for s in schemas]
        # The user's qualified table survives; the bare injected schema is dropped.
        assert "public.database_stats_queries" in names
        assert DATABASE_STATS_QUERIES not in names
        assert DATABASE_STATS_SERVER in names


@pytest.fixture
def autocommit_pg_connection():
    # Raw autocommit connection to the test DB — the same way the collector connects in
    # production (each probe is its own transaction).
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


class TestPostgresStatsCollectors:
    """Runs the collectors against the Django test database itself — a real Postgres with
    real statistics catalogs, plus the realistic degradation case of pg_stat_statements
    usually not being installed."""

    @pytest.mark.django_db
    def test_tables_snapshot_matches_declared_columns(self, autocommit_pg_connection):
        rows = _collect_tables(autocommit_pg_connection, logger, *_snapshot_base())
        assert rows, "expected at least one user table in the test database"
        assert set(rows[0].keys()) == _column_names(DATABASE_STATS_TABLES)

    @pytest.mark.django_db
    def test_indexes_snapshot_matches_declared_columns(self, autocommit_pg_connection):
        rows = _collect_indexes(autocommit_pg_connection, logger, *_snapshot_base())
        assert rows, "expected at least one index in the test database"
        assert set(rows[0].keys()) == _column_names(DATABASE_STATS_INDEXES)

    @pytest.mark.django_db
    def test_server_snapshot_has_core_metrics(self, autocommit_pg_connection):
        rows = _collect_server(autocommit_pg_connection, logger, *_snapshot_base())
        assert rows
        assert all(set(r.keys()) == _column_names(DATABASE_STATS_SERVER) for r in rows)
        metric_names = {r["metric_name"] for r in rows}
        assert {"server_version", "connections_total", "numbackends", "setting_max_connections"} <= metric_names

    @pytest.mark.django_db
    def test_queries_snapshot_degrades_without_extension(self, autocommit_pg_connection):
        rows = _collect_queries(autocommit_pg_connection, logger, *_snapshot_base())
        with autocommit_pg_connection.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_extension WHERE extname = 'pg_stat_statements'")
            installed = cur.fetchone()[0] > 0
        if installed:
            assert rows and set(rows[0].keys()) == _column_names(DATABASE_STATS_QUERIES)
        else:
            assert rows == []

    @pytest.mark.django_db
    def test_collector_failure_yields_empty_snapshot(self, autocommit_pg_connection):
        def _boom(conn, log, collected_at, snapshot_id):
            raise RuntimeError("family exploded")

        with patch.dict(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.stats._COLLECTORS",
            {DATABASE_STATS_SERVER: _boom},
        ):
            sd = django_connection.settings_dict
            response = postgres_database_stats_source(
                tunnel=lambda: _fake_tunnel_to(sd),
                user=sd["USER"] or "",
                password=sd["PASSWORD"] or "",
                database=sd["NAME"],
                schema_name=DATABASE_STATS_SERVER,
                require_ssl=False,
                logger=logger,
            )
            assert list(cast(Iterable[Any], response.items())) == []


def _snapshot_base():
    from datetime import UTC, datetime

    return datetime.now(UTC), uuid.uuid4().hex


class _ScriptedCursor:
    """Minimal psycopg cursor stand-in: routes execute() by SQL substring.

    Lets tests drive the collector paths the CI database can't produce — an installed
    pg_stat_statements (with modern or legacy columns, masked text), failing probes, a
    standby server — without a network connection.
    """

    def __init__(self, script: list[tuple[str, Any]], executed: list[str] | None = None):
        self._script = script
        self._executed = executed if executed is not None else []
        self._rows: list[tuple] = []

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
                self._rows = list(outcome)
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


class TestCollectQueriesScripted:
    _EXTENSION = ("FROM pg_extension e", [("public",)])

    def test_modern_columns_with_masked_text(self):
        script = [
            self._EXTENSION,
            (
                "total_exec_time",
                [
                    ("123", "SELECT * FROM users WHERE id = $1", 10, 250.0, 25.0, 10, 5, 1, 0),
                    ("456", "<insufficient privilege>", 3, 90.0, None, 3, None, None, None),
                ],
            ),
        ]
        rows = _collect_queries(cast(Any, _ScriptedConnection(script)), logger, *_snapshot_base())

        assert [r["query_fingerprint"] for r in rows] == ["123", "456"]
        assert rows[0]["query_text"] == "SELECT * FROM users WHERE id = $1"
        assert rows[0]["total_exec_time_ms"] == 250.0
        # Masked text becomes NULL; counters stay usable.
        assert rows[1]["query_text"] is None
        assert rows[1]["mean_exec_time_ms"] is None
        assert rows[1]["calls"] == 3

    def test_legacy_column_names_fall_back(self):
        script = [
            self._EXTENSION,
            ("total_exec_time", psycopg.errors.UndefinedColumn("no such column")),
            ("total_time", [("789", "SELECT 1", 1, 5.0, 5.0, 1, 0, 0, 0)]),
        ]
        rows = _collect_queries(cast(Any, _ScriptedConnection(script)), logger, *_snapshot_base())
        assert len(rows) == 1
        assert rows[0]["query_fingerprint"] == "789"
        assert rows[0]["total_exec_time_ms"] == 5.0

    def test_unexpected_column_set_skips_family(self):
        script = [
            self._EXTENSION,
            ("total_exec_time", psycopg.errors.UndefinedColumn("no such column")),
            ("total_time", psycopg.errors.UndefinedColumn("still no such column")),
        ]
        assert _collect_queries(cast(Any, _ScriptedConnection(script)), logger, *_snapshot_base()) == []

    def test_statements_are_scoped_to_the_connected_database(self):
        # pg_stat_statements is cluster-wide; without the dbid filter another database's
        # query text would land in this team's warehouse table.
        script = [self._EXTENSION, ("total_exec_time", [])]
        conn = _ScriptedConnection(script)
        _collect_queries(cast(Any, conn), logger, *_snapshot_base())

        statements_query = next(q for q in conn.executed if "shared_blks_hit" in q)
        assert "dbid = (SELECT oid FROM pg_database WHERE datname = current_database())" in statements_query


class TestCollectServerScripted:
    def test_failing_probe_is_isolated_and_standby_skips_slots(self):
        script = [
            ("SHOW server_version", RuntimeError("probe exploded")),
            ("FROM pg_stat_database", []),  # no row for current_database() → probe returns nothing
            ("FROM pg_stat_activity", [(7,)]),
            ("FROM pg_settings", [("max_connections", "100", None)]),
            ("FROM pg_extension", [(1,)]),
            ("pg_is_in_recovery", [(True,)]),  # standby: replication-slot lag not measurable
        ]
        rows = _collect_server(cast(Any, _ScriptedConnection(script)), logger, *_snapshot_base())
        metrics = {r["metric_name"] for r in rows}

        assert "server_version" not in metrics  # failed probe skipped, others survived
        assert "numbackends" not in metrics  # empty pg_stat_database row
        assert "connections_total" in metrics
        assert "setting_max_connections" in metrics
        assert "extension_pg_stat_statements" in metrics
        assert "replication_slot_lag_bytes" not in metrics

    def test_replication_slot_lag_on_primary(self):
        script = [
            ("SHOW server_version", [("16.4",)]),
            ("FROM pg_stat_database", [(1, 2, 3, 4, 5, 6, 7, 8)]),
            ("FROM pg_stat_activity", [(1,)]),
            ("FROM pg_settings", []),
            ("FROM pg_extension", [(0,)]),
            ("pg_is_in_recovery", [(False,)]),
            ("FROM pg_replication_slots", [("cdc_slot", True, 12345.0), ("stale_slot", False, None)]),
        ]
        conn = _ScriptedConnection(script)
        rows = _collect_server(cast(Any, conn), logger, *_snapshot_base())
        slots = {r["metric_text"]: r["metric_value"] for r in rows if r["metric_name"] == "replication_slot_lag_bytes"}

        assert slots == {"cdc_slot": 12345.0, "stale_slot": None}
        # Slots are a cluster-wide catalog — another database's slot names must not leak.
        slots_query = next(q for q in conn.executed if "pg_replication_slots" in q)
        assert "WHERE database = current_database()" in slots_query


@contextmanager
def _fake_tunnel_to(settings_dict):
    yield (settings_dict["HOST"] or "localhost", int(settings_dict["PORT"] or 5432))


class TestStatsSourceRouting:
    @pytest.mark.django_db
    def test_source_for_pipeline_routes_stats_schema_to_collector(self, team):
        sd = django_connection.settings_dict
        source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=team,
            status="running",
            source_type="Postgres",
            job_inputs={},
        )
        # Pre-SSL-cutoff creation date so the routing test can connect to the local
        # (non-SSL) test database.
        ExternalDataSource.objects.filter(id=source.id).update(created_at="2023-01-01T00:00:00Z")
        source.refresh_from_db()
        schema_row = ExternalDataSchema.objects.create(
            name=DATABASE_STATS_SERVER,
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
        inputs = SourceInputs(
            schema_name=DATABASE_STATS_SERVER,
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

        response = PostgresSource().source_for_pipeline(config, inputs)

        assert response.name == DATABASE_STATS_SERVER
        rows = list(cast(Iterable[Any], response.items()))
        assert rows, "expected server metrics from the test database"
        assert {r["metric_name"] for r in rows} >= {"server_version", "connections_total"}
        assert all(set(r.keys()) == _column_names(DATABASE_STATS_SERVER) for r in rows)

    @pytest.mark.django_db
    def test_colliding_real_table_syncs_as_a_table_despite_toggle(self, team):
        # Greptile finding on #72975: a user's own bare table named database_stats_server
        # must keep the normal table-sync path. Its row carries source_table_name in the
        # reconciled schema_metadata; injected stats rows never do.
        source = ExternalDataSource.objects.create(
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            team=team,
            status="running",
            source_type="Postgres",
            job_inputs={},
        )
        schema_row = ExternalDataSchema.objects.create(
            name=DATABASE_STATS_SERVER,
            team_id=team.pk,
            source_id=source.pk,
            sync_type="full_refresh",
            sync_type_config={
                "schema_metadata": {"source_schema": "public", "source_table_name": "database_stats_server"}
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
        inputs = SourceInputs(
            schema_name=DATABASE_STATS_SERVER,
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
        sentinel = object()
        base = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source"
        with (
            patch(f"{base}.postgres_source", return_value=MagicMock(name="table_response")) as table_source,
            patch(f"{base}.postgres_database_stats_source", return_value=sentinel) as stats_source,
        ):
            PostgresSource().source_for_pipeline(config, inputs)

        table_source.assert_called_once()
        stats_source.assert_not_called()
