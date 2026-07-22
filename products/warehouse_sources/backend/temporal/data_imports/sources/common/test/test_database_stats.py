from types import SimpleNamespace
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

import structlog

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.database_stats import (
    DATABASE_STATS_SCHEMA_NAMES,
    DATABASE_STATS_SERVER,
    build_database_stats_source_response,
    database_stats_enabled,
    is_database_stats_schema,
    maybe_append_database_stats_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
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

    def validate_credentials(self, config, team_id):  # pragma: no cover - not exercised
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


class TestSQLSourceStatsRouting:
    def test_stats_schema_with_toggle_enabled_requires_override(self):
        source = _StubSQLSource(MagicMock())
        config = SimpleNamespace(database_stats=SimpleNamespace(enabled=True))
        with pytest.raises(NotImplementedError):
            source.source_for_pipeline(cast(Any, config), _inputs(DATABASE_STATS_SERVER))

    def test_stats_named_schema_without_toggle_goes_to_build_pipeline(self):
        # A user's own table that happens to be named database_stats_* must sync normally
        # on sources that haven't opted in.
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
        assert list(response.items()) == []

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
        rows = list(response.items())
        assert rows[0]["snapshot_id"] == seen["snapshot_id"]
        assert rows[0]["collected_at"] == seen["collected_at"]
        assert is_database_stats_schema(DATABASE_STATS_SERVER)
