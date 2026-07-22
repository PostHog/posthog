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
    DATABASE_STATS_COLUMNS,
    DATABASE_STATS_SCHEMA_NAMES,
    DATABASE_STATS_SERVER,
    build_database_stats_source_response,
    build_database_stats_source_schemas,
    database_stats_enabled,
    is_database_stats_schema,
    is_database_stats_schema_row,
    maybe_append_database_stats_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_default_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource

logger = structlog.get_logger()


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
            declared = {column_name for column_name, _, _ in DATABASE_STATS_COLUMNS[name]}
            assert {"collected_at", "snapshot_id"} <= declared


class TestMaybeAppendDatabaseStatsSchemas:
    def test_config_without_toggle_returns_listing_unchanged(self):
        schemas = [_discovered("users")]
        assert maybe_append_database_stats_schemas(SimpleNamespace(), schemas, None) is schemas

    def test_disabled_toggle_returns_listing_unchanged(self):
        schemas = [_discovered("users")]
        config = SimpleNamespace(database_stats=SimpleNamespace(enabled=False))
        assert maybe_append_database_stats_schemas(config, schemas, None) is schemas

    def test_enabled_toggle_appends_stats_schemas(self):
        config = SimpleNamespace(database_stats=SimpleNamespace(enabled=True))
        result = maybe_append_database_stats_schemas(config, [_discovered("users")], None)
        assert [s.name for s in result] == ["users", *DATABASE_STATS_SCHEMA_NAMES]

    def test_names_filter_limits_appended_schemas(self):
        config = SimpleNamespace(database_stats=SimpleNamespace(enabled=True))
        result = maybe_append_database_stats_schemas(config, [_discovered("users")], ["users", DATABASE_STATS_SERVER])
        assert [s.name for s in result] == ["users", DATABASE_STATS_SERVER]


class _StubSQLSource(SQLSource):
    """Minimal concrete SQLSource: only what source_for_pipeline touches."""

    def __init__(self, implementation: Any):
        self._implementation = implementation

    @property
    def get_implementation(self) -> Any:
        return self._implementation

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


def _inputs(schema_name: str) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
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
    def _source_with_empty_listing(self) -> _StubSQLSource:
        implementation = MagicMock()
        implementation.get_columns.return_value = {}
        return _StubSQLSource(implementation)

    def test_empty_listing_still_surfaces_stats_schemas_when_enabled(self):
        # A database with no (matching) user tables — or a names filter listing only
        # stats schemas — must still surface them when the source opted in.
        config = SimpleNamespace(database_stats=SimpleNamespace(enabled=True))
        schemas = self._source_with_empty_listing().get_schemas(cast(Any, config), team_id=1)
        assert [s.name for s in schemas] == list(DATABASE_STATS_SCHEMA_NAMES)

    def test_empty_listing_stays_empty_without_toggle(self):
        schemas = self._source_with_empty_listing().get_schemas(cast(Any, SimpleNamespace()), team_id=1)
        assert schemas == []


class TestIsDatabaseStatsSchemaRow:
    def test_non_stats_name_is_never_a_stats_row(self):
        assert is_database_stats_schema_row("users", None) is False

    @pytest.mark.parametrize("schema_metadata", [None, {}, {"source_table_name": None}])
    def test_stats_name_without_source_table_is_a_stats_row(self, schema_metadata):
        assert is_database_stats_schema_row(DATABASE_STATS_SERVER, schema_metadata) is True

    def test_stats_name_backed_by_a_real_table_is_not_a_stats_row(self):
        metadata = {"source_table_name": "database_stats_server", "source_schema": "public"}
        assert is_database_stats_schema_row(DATABASE_STATS_SERVER, metadata) is False


def _schema_row(team, name: str, schema_metadata: dict | None) -> ExternalDataSchema:
    import uuid as _uuid

    source = ExternalDataSource.objects.create(
        source_id=str(_uuid.uuid4()),
        connection_id=str(_uuid.uuid4()),
        destination_id=str(_uuid.uuid4()),
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
    def test_stats_schema_with_toggle_enabled_requires_override(self, team):
        row = _schema_row(team, DATABASE_STATS_SERVER, None)
        source = _StubSQLSource(MagicMock())
        config = SimpleNamespace(database_stats=SimpleNamespace(enabled=True))
        inputs = _inputs(DATABASE_STATS_SERVER)
        inputs.schema_id = str(row.id)
        with pytest.raises(NotImplementedError):
            source.source_for_pipeline(cast(Any, config), inputs)

    @pytest.mark.django_db
    def test_colliding_real_table_goes_to_build_pipeline_despite_toggle(self, team):
        # A user's own table named database_stats_* (its row carries source_table_name)
        # must keep syncing as a table even with statistics enabled.
        row = _schema_row(
            team,
            DATABASE_STATS_SERVER,
            {"source_table_name": "database_stats_server", "source_schema": "public"},
        )
        implementation = MagicMock()
        source = _StubSQLSource(implementation)
        config = SimpleNamespace(database_stats=SimpleNamespace(enabled=True))
        inputs = _inputs(DATABASE_STATS_SERVER)
        inputs.schema_id = str(row.id)

        source.source_for_pipeline(cast(Any, config), inputs)

        implementation.build_pipeline.assert_called_once_with(config, inputs)

    def test_stats_named_schema_without_toggle_goes_to_build_pipeline(self):
        # No opt-in: short-circuits before any row lookup, so no database needed.
        implementation = MagicMock()
        source = _StubSQLSource(implementation)
        config = SimpleNamespace()
        inputs = _inputs(DATABASE_STATS_SERVER)

        source.source_for_pipeline(cast(Any, config), inputs)

        implementation.build_pipeline.assert_called_once_with(config, inputs)

    def test_regular_schema_goes_to_build_pipeline_with_toggle_enabled(self):
        implementation = MagicMock()
        source = _StubSQLSource(implementation)
        config = SimpleNamespace(database_stats=SimpleNamespace(enabled=True))
        inputs = _inputs("users")

        source.source_for_pipeline(cast(Any, config), inputs)

        implementation.build_pipeline.assert_called_once_with(config, inputs)


class TestBuildDatabaseStatsSourceResponse:
    def test_unknown_schema_name_raises(self):
        with pytest.raises(ValueError):
            build_database_stats_source_response(
                schema_name="not_a_stats_schema",
                collectors={},
                open_connection=MagicMock(),
                logger=logger,
            )

    def test_collector_failure_yields_empty_snapshot(self):
        def _boom(conn, log, collected_at, snapshot_id):
            raise RuntimeError("family exploded")

        open_connection = MagicMock()
        open_connection.return_value.__enter__ = MagicMock(return_value=object())
        open_connection.return_value.__exit__ = MagicMock(return_value=False)

        response = build_database_stats_source_response(
            schema_name=DATABASE_STATS_SERVER,
            collectors={DATABASE_STATS_SERVER: _boom},
            open_connection=open_connection,
            logger=logger,
        )
        assert list(cast(Iterable[Any], response.items())) == []

    def test_rows_are_stamped_with_shared_snapshot_identity(self):
        seen: dict[str, Any] = {}

        def _collector(conn, log, collected_at, snapshot_id):
            seen["collected_at"] = collected_at
            seen["snapshot_id"] = snapshot_id
            return [{"collected_at": collected_at, "snapshot_id": snapshot_id, "metric_name": "x"}]

        open_connection = MagicMock()
        open_connection.return_value.__enter__ = MagicMock(return_value=object())
        open_connection.return_value.__exit__ = MagicMock(return_value=False)

        response = build_database_stats_source_response(
            schema_name=DATABASE_STATS_SERVER,
            collectors={DATABASE_STATS_SERVER: _collector},
            open_connection=open_connection,
            logger=logger,
        )
        rows = list(cast(Iterable[Any], response.items()))
        assert rows[0]["snapshot_id"] == seen["snapshot_id"]
        assert rows[0]["collected_at"] == seen["collected_at"]
        assert is_database_stats_schema(DATABASE_STATS_SERVER)
