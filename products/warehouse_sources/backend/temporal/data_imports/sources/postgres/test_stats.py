import uuid
from contextlib import contextmanager
from typing import Any, cast

import pytest
from unittest.mock import patch

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
    build_database_stats_source_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import build_default_schemas
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


class TestBuildDatabaseStatsSourceSchemas:
    def test_builds_all_four_schemas_with_append_defaults(self):
        schemas = build_database_stats_source_schemas(["public.users", "orders"])

        assert [s.name for s in schemas] == list(DATABASE_STATS_SCHEMA_NAMES)
        defaults = build_default_schemas(schemas)
        for default in defaults:
            assert default["should_sync"] is True
            assert default["sync_type"] == "append"
            assert default["incremental_field"] == "collected_at"

    def test_collision_with_discovered_table_drops_that_schema(self):
        # Bare↔qualified equivalence: `public.database_stats_server` must collide with the
        # bare injected name, matching sync_old_schemas_with_new_schemas' matching rules.
        schemas = build_database_stats_source_schemas(["public.database_stats_server"])
        assert DATABASE_STATS_SERVER not in [s.name for s in schemas]
        assert len(schemas) == len(DATABASE_STATS_SCHEMA_NAMES) - 1

    def test_every_schema_declares_snapshot_columns(self):
        for name in DATABASE_STATS_SCHEMA_NAMES:
            assert {"collected_at", "snapshot_id"} <= _column_names(name)


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
            assert list(response.items()) == []


def _snapshot_base():
    from datetime import UTC, datetime

    return datetime.now(UTC), uuid.uuid4().hex


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
        rows = list(cast(Any, response.items)())
        assert rows, "expected server metrics from the test database"
        assert {r["metric_name"] for r in rows} >= {"server_version", "connections_total"}
        assert all(set(r.keys()) == _column_names(DATABASE_STATS_SERVER) for r in rows)
