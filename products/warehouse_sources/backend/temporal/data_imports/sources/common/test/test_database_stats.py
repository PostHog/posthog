import uuid
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

import structlog

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.database_stats import (
    DatabaseStatsCatalog,
    build_database_stats_schemas,
    build_database_stats_source_response,
    database_stats_enabled,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_default_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource

logger = structlog.get_logger()


def _catalog(table_name: str = "some_stat_view", **kwargs) -> DatabaseStatsCatalog:
    return DatabaseStatsCatalog(
        table_name=table_name,
        description=f"Snapshots of {table_name}.",
        collector=kwargs.pop("collector", MagicMock(return_value=[])),
        **kwargs,
    )


_CATALOGS = {c.table_name: c for c in (_catalog("some_stat_view"), _catalog("other_stat_view"))}
_COLUMNS = {
    "some_stat_view": [("relname", "name", True), ("seq_scan", "bigint", True)],
    "other_stat_view": [("datname", "name", True)],
}


def _discovered(name: str) -> SourceSchema:
    return SourceSchema(name=name, supports_incremental=False, supports_append=False)


class TestDatabaseStatsEnabled:
    def test_config_without_toggle_attribute_is_disabled(self):
        # Every non-SQL-family source config today: no `database_stats` attribute at all.
        assert database_stats_enabled(SimpleNamespace()) is False

    @pytest.mark.parametrize(
        "stats_config,expected",
        [(None, False), (SimpleNamespace(enabled=False), False), (SimpleNamespace(enabled=True), True)],
    )
    def test_toggle_states(self, stats_config, expected):
        assert database_stats_enabled(SimpleNamespace(database_stats=stats_config)) is expected


class TestBuildDatabaseStatsSchemas:
    def test_schemas_declare_snapshot_columns_then_the_catalog_s_own(self):
        schemas = build_database_stats_schemas(_CATALOGS, _COLUMNS, ["public.users"])

        assert [s.name for s in schemas] == [
            "some_stat_view",
            "other_stat_view",
        ]
        assert [c[0] for c in schemas[0].columns] == ["collected_at", "snapshot_id", "relname", "seq_scan"]

    def test_computed_columns_are_appended(self):
        catalogs = {"some_stat_view": _catalog(computed_columns=(("total_size_bytes", "bigint", True),))}
        schemas = build_database_stats_schemas(catalogs, _COLUMNS, [])
        assert [c[0] for c in schemas[0].columns][-1] == "total_size_bytes"

    def test_static_columns_replace_the_server_lookup(self):
        catalogs = {"derived": _catalog("derived", static_columns=(("state", "text", True),))}
        schemas = build_database_stats_schemas(catalogs, {}, [])
        assert [c[0] for c in schemas[0].columns] == ["collected_at", "snapshot_id", "state"]

    def test_catalog_the_server_does_not_expose_is_skipped(self):
        # e.g. pg_stat_statements when the extension isn't installed: no columns, so the
        # table isn't offered at all rather than declared empty.
        schemas = build_database_stats_schemas(_CATALOGS, {"some_stat_view": _COLUMNS["some_stat_view"]}, [])
        assert [s.name for s in schemas] == ["some_stat_view"]

    def test_snapshots_default_to_append_on_collected_at(self):
        defaults = build_default_schemas(build_database_stats_schemas(_CATALOGS, _COLUMNS, []))
        for default in defaults:
            assert default["should_sync"] is True
            assert default["sync_type"] == "append"
            assert default["incremental_field"] == "collected_at"

    def test_collision_with_a_discovered_table_drops_that_catalog(self):
        schemas = build_database_stats_schemas(_CATALOGS, _COLUMNS, ["some_stat_view"])
        assert [s.name for s in schemas] == ["other_stat_view"]

    def test_names_filter_limits_the_tables(self):
        schemas = build_database_stats_schemas(_CATALOGS, _COLUMNS, [], ["users", "other_stat_view"])
        assert [s.name for s in schemas] == ["other_stat_view"]


class _StubSQLSource(SQLSource):
    """Minimal concrete SQLSource: only what get_schemas and source_for_pipeline touch."""

    def __init__(self, implementation: Any, catalogs: Any = None, stats_columns: Any = None):
        self._implementation = implementation
        self.database_stats_catalogs = catalogs or {}
        self._stats_columns = stats_columns or {}

    @property
    def get_implementation(self) -> Any:
        return self._implementation

    def fetch_database_stats_columns(self, conn: Any, config: Any) -> dict[str, list[tuple[str, str, bool]]]:
        return self._stats_columns

    @property
    def source_type(self):  # pragma: no cover - not exercised
        raise NotImplementedError

    @property
    def get_source_config(self):  # pragma: no cover - not exercised
        raise NotImplementedError

    def validate_credentials(  # pragma: no cover - not exercised
        self,
        config: Any,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        raise NotImplementedError


def _inputs(schema_name: str, schema_id: str = "schema-id") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id=schema_id,
        source_id="source-id",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=logger,
        reset_pipeline=False,
    )


class TestSQLSourceGetSchemasStatsInjection:
    def _source(self, columns_by_table: dict) -> _StubSQLSource:
        implementation = MagicMock()
        implementation.get_columns.return_value = columns_by_table
        return _StubSQLSource(implementation, catalogs=_CATALOGS, stats_columns=_COLUMNS)

    def test_empty_listing_still_surfaces_stats_tables_when_enabled(self):
        # A database with no (matching) user tables — or a names filter listing only
        # statistics tables — must still surface them when the source opted in.
        config = SimpleNamespace(database_stats=SimpleNamespace(enabled=True))
        schemas = self._source({}).get_schemas(cast(Any, config), team_id=1)
        assert [s.name for s in schemas] == [
            "some_stat_view",
            "other_stat_view",
        ]

    def test_empty_listing_stays_empty_without_toggle(self):
        schemas = self._source({}).get_schemas(cast(Any, SimpleNamespace()), team_id=1)
        assert schemas == []

    def test_source_without_catalogs_is_untouched(self):
        implementation = MagicMock()
        implementation.get_columns.return_value = {}
        config = SimpleNamespace(database_stats=SimpleNamespace(enabled=True))
        assert _StubSQLSource(implementation).get_schemas(cast(Any, config), team_id=1) == []


def _schema_row(team, name: str, schema_metadata: dict | None) -> ExternalDataSchema:
    source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        destination_id=str(uuid.uuid4()),
        team=team,
        status="running",
        source_type="Postgres",
        job_inputs={},
    )
    return ExternalDataSchema.objects.create(
        name=name,
        team_id=team.pk,
        source_id=source.pk,
        sync_type="append",
        sync_type_config={"schema_metadata": schema_metadata} if schema_metadata is not None else {},
    )


class TestSQLSourceStatsRouting:
    @pytest.mark.django_db
    def test_stats_table_with_toggle_enabled_requires_override(self, team):
        row = _schema_row(team, "some_stat_view", None)
        source = _StubSQLSource(MagicMock(), catalogs=_CATALOGS)
        config = SimpleNamespace(database_stats=SimpleNamespace(enabled=True))
        with pytest.raises(NotImplementedError):
            source.source_for_pipeline(cast(Any, config), _inputs(row.name, str(row.id)))

    def test_source_without_catalogs_routes_everything_to_build_pipeline(self):
        # No catalogs means no statistics feature: even a name matching another source's
        # catalog syncs as an ordinary table.
        implementation = MagicMock()
        source = _StubSQLSource(implementation)
        config = SimpleNamespace(database_stats=SimpleNamespace(enabled=True))
        inputs = _inputs("some_stat_view")

        source.source_for_pipeline(cast(Any, config), inputs)

        implementation.build_pipeline.assert_called_once_with(config, inputs)

    def test_regular_schema_goes_to_build_pipeline_with_toggle_enabled(self):
        implementation = MagicMock()
        source = _StubSQLSource(implementation, catalogs=_CATALOGS)
        config = SimpleNamespace(database_stats=SimpleNamespace(enabled=True))
        inputs = _inputs("public.users")

        source.source_for_pipeline(cast(Any, config), inputs)

        implementation.build_pipeline.assert_called_once_with(config, inputs)


class TestBuildDatabaseStatsSourceResponse:
    def _open_connection(self) -> MagicMock:
        open_connection = MagicMock()
        open_connection.return_value.__enter__ = MagicMock(return_value=object())
        open_connection.return_value.__exit__ = MagicMock(return_value=False)
        return open_connection

    def test_unknown_table_raises(self):
        with pytest.raises(ValueError):
            build_database_stats_source_response(
                schema_name="not_a_catalog",
                catalogs=_CATALOGS,
                collectors={},
                open_connection=MagicMock(),
                logger=logger,
            )

    def test_collector_failure_yields_an_empty_snapshot(self):
        def _boom(conn, log, collected_at, snapshot_id):
            raise RuntimeError("catalog exploded")

        response = build_database_stats_source_response(
            schema_name="some_stat_view",
            catalogs=_CATALOGS,
            collectors={"some_stat_view": _boom},
            open_connection=self._open_connection(),
            logger=logger,
        )
        assert list(cast(Iterable[Any], response.items())) == []

    def test_rows_are_stamped_with_one_shared_snapshot_identity(self):
        seen: dict[str, Any] = {}

        def _collector(conn, log, collected_at, snapshot_id):
            seen["collected_at"] = collected_at
            seen["snapshot_id"] = snapshot_id
            return [{"collected_at": collected_at, "snapshot_id": snapshot_id, "relname": "users"}]

        response = build_database_stats_source_response(
            schema_name="some_stat_view",
            catalogs=_CATALOGS,
            collectors={"some_stat_view": _collector},
            open_connection=self._open_connection(),
            logger=logger,
        )
        rows = list(cast(Iterable[Any], response.items()))
        assert rows[0]["snapshot_id"] == seen["snapshot_id"]
        assert rows[0]["collected_at"] == seen["collected_at"]
