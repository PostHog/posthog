from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from typing import Any

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from posthog.schema import SourceConfig

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.config import Config
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import (
    SQLSource,
    reconcile_source_schema_metadata,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.implementation import (
    SourceMetadata,
    SQLSourceImplementation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.incremental import (
    IncrementalFieldFilter,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType


@dataclasses.dataclass
class _FakeConfig(Config):
    name: str = "fake"


def _fake_filter(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    """Treat any column typed 'timestamp' as incremental-capable."""
    return [
        (name, IncrementalFieldType.Timestamp, nullable)
        for name, data_type, nullable in columns
        if data_type == "timestamp"
    ]


@dataclasses.dataclass
class _FakeImplData:
    columns_by_table: dict[str, list[tuple[str, str, bool]]] = dataclasses.field(default_factory=dict)
    primary_keys_by_table: dict[str, list[str] | None] = dataclasses.field(default_factory=dict)
    row_counts_by_table: dict[str, int | None] = dataclasses.field(default_factory=dict)
    foreign_keys_by_table: dict[str, list[tuple[str, str, str]]] = dataclasses.field(default_factory=dict)
    source_metadata: SourceMetadata = dataclasses.field(default_factory=SourceMetadata)
    cdc_by_table: dict[str, bool] = dataclasses.field(default_factory=dict)


class _FakeImplementation(SQLSourceImplementation[_FakeConfig, object, Any]):
    """Records the arguments it receives so tests can assert on the wiring."""

    def __init__(self, data: _FakeImplData | None = None) -> None:
        self.data = data or _FakeImplData()
        self.get_columns_calls: list[tuple[list[str] | None]] = []
        self.get_primary_keys_called = False
        self.get_row_counts_called = False
        self.get_foreign_keys_called = False

    @contextmanager
    def connect(self, config: _FakeConfig):
        yield object()

    def get_columns(
        self, conn: object, config: _FakeConfig, names: list[str] | None
    ) -> dict[str, list[tuple[str, str, bool]]]:
        self.get_columns_calls.append((names,))
        if names is None:
            return self.data.columns_by_table
        return {k: v for k, v in self.data.columns_by_table.items() if k in names}

    def get_primary_keys(self, conn: object, config: _FakeConfig, tables: list[str]) -> dict[str, list[str] | None]:
        self.get_primary_keys_called = True
        return self.data.primary_keys_by_table

    def get_row_counts(self, conn: object, config: _FakeConfig, tables: list[str]) -> dict[str, int | None]:
        self.get_row_counts_called = True
        return self.data.row_counts_by_table

    def get_foreign_keys(
        self, conn: object, config: _FakeConfig, tables: list[str]
    ) -> dict[str, list[tuple[str, str, str]]]:
        self.get_foreign_keys_called = True
        return self.data.foreign_keys_by_table

    def get_source_metadata(self, conn: object, config: _FakeConfig, tables: list[str]) -> SourceMetadata:
        return self.data.source_metadata

    def get_cdc_support(self, conn: object, config: _FakeConfig, tables: list[str]) -> dict[str, bool]:
        return self.data.cdc_by_table

    def get_incremental_filter(self) -> IncrementalFieldFilter:
        return _fake_filter

    def build_pipeline(self, config: _FakeConfig, inputs: SourceInputs) -> SourceResponse:
        raise NotImplementedError("not exercised in get_schemas tests")


class _FakeSQLSource(SQLSource[_FakeConfig]):
    def __init__(self, impl: _FakeImplementation) -> None:
        self._implementation = impl

    @property
    def get_implementation(self) -> _FakeImplementation:
        return self._implementation

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POSTGRES

    @property
    def get_source_config(self) -> SourceConfig:
        return MagicMock(spec=SourceConfig)


def _make_source(**data: Any) -> tuple[_FakeSQLSource, _FakeImplementation]:
    impl = _FakeImplementation(_FakeImplData(**data))
    return _FakeSQLSource(impl), impl


class TestGetSchemas:
    def test_returns_one_source_schema_per_table(self) -> None:
        source, _ = _make_source(
            columns_by_table={
                "messages": [("id", "int", False), ("ts", "timestamp", False)],
                "users": [("id", "int", False)],
            }
        )
        result = source.get_schemas(_FakeConfig(), team_id=1)
        assert {s.name for s in result} == {"messages", "users"}

    def test_incremental_fields_derived_via_filter(self) -> None:
        source, _ = _make_source(columns_by_table={"messages": [("id", "int", False), ("ts", "timestamp", False)]})
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        fields: list[Any] = list(schema.incremental_fields)
        assert len(fields) == 1
        assert fields[0]["field"] == "ts"
        assert schema.supports_incremental is True
        assert schema.supports_append is True

    def test_no_incremental_fields_disables_incremental_flags(self) -> None:
        source, _ = _make_source(columns_by_table={"tbl": [("id", "int", False)]})
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.incremental_fields == []
        assert schema.supports_incremental is False

    def test_detected_primary_keys_passed_through(self) -> None:
        source, _ = _make_source(
            columns_by_table={"messages": [("id", "int", False)]},
            primary_keys_by_table={"messages": ["id"]},
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.detected_primary_keys == ["id"]

    def test_falls_back_to_id_column_when_no_pk_detected(self) -> None:
        source, _ = _make_source(
            columns_by_table={"messages": [("id", "int", False), ("body", "text", True)]},
            primary_keys_by_table={"messages": None},
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.detected_primary_keys == ["id"]

    def test_no_pk_fallback_when_no_id_column(self) -> None:
        source, _ = _make_source(columns_by_table={"messages": [("body", "text", True)]})
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.detected_primary_keys is None

    def test_row_counts_passed_through_when_with_counts_true(self) -> None:
        source, impl = _make_source(
            columns_by_table={"messages": [("id", "int", False)]},
            row_counts_by_table={"messages": 42},
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1, with_counts=True)
        assert schema.row_count == 42
        assert impl.get_row_counts_called is True

    def test_row_counts_skipped_when_with_counts_false(self) -> None:
        source, impl = _make_source(
            columns_by_table={"messages": [("id", "int", False)]},
            row_counts_by_table={"messages": 42},
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1, with_counts=False)
        assert schema.row_count is None
        assert impl.get_row_counts_called is False

    def test_foreign_keys_passed_through(self) -> None:
        source, _ = _make_source(
            columns_by_table={"messages": [("id", "int", False)]},
            foreign_keys_by_table={"messages": [("author_id", "users", "id")]},
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.foreign_keys == [("author_id", "users", "id")]

    @pytest.mark.parametrize("names", [None, ["messages"]])
    def test_names_forwarded_to_get_columns(self, names: list[str] | None) -> None:
        source, impl = _make_source(
            columns_by_table={
                "messages": [("id", "int", False)],
                "users": [("id", "int", False)],
            }
        )
        source.get_schemas(_FakeConfig(), team_id=1, names=names)
        assert impl.get_columns_calls == [(names,)]

    def test_empty_discovery_returns_empty_list(self) -> None:
        source, _ = _make_source(columns_by_table={})
        assert source.get_schemas(_FakeConfig(), team_id=1) == []

    def test_source_metadata_passed_through(self) -> None:
        source, _ = _make_source(
            columns_by_table={"t": [("id", "int", False)]},
            source_metadata=SourceMetadata(
                catalog_by_table={"t": "my_db"},
                schema_by_table={"t": "public"},
                table_name_by_table={"t": "original_t"},
            ),
            cdc_by_table={"t": True},
        )
        [schema] = source.get_schemas(_FakeConfig(), team_id=1)
        assert schema.source_catalog == "my_db"
        assert schema.source_schema == "public"
        assert schema.source_table_name == "original_t"
        assert schema.supports_cdc is True


class TestDefaultNonRetryableErrors:
    @pytest.mark.parametrize(
        "key,expected_substring",
        [
            ("Source column type changed", "reset and fully re-sync"),
            ("Cannot build decimal array from values", "decimal storage limits"),
        ],
    )
    def test_includes_expected_entry(self, key: str, expected_substring: str) -> None:
        # Calling without an instance proves the classmethod shape too — the
        # eventual subclass call site is `cls.default_non_retryable_errors()`.
        errors = SQLSource.default_non_retryable_errors()
        assert key in errors
        message = errors[key]
        assert message is not None
        assert expected_substring in message

    def test_returns_exactly_the_two_shared_entries(self) -> None:
        errors = SQLSource.default_non_retryable_errors()
        assert isinstance(errors, dict)
        assert len(errors) == 2


class TestReconcileSourceSchemaMetadata(BaseTest):
    """The driver-agnostic reconcile helper that `SQLSource` and `ClickHouseSource` share."""

    def _source(self) -> ExternalDataSource:
        return ExternalDataSource.objects.create(team=self.team, source_type=ExternalDataSourceType.CLICKHOUSE)

    def _schema(self, source: ExternalDataSource, name: str = "messages", **kwargs: Any) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(team=self.team, source=source, name=name, **kwargs)

    @staticmethod
    def _source_schema(name: str = "messages", **kwargs: Any) -> SourceSchema:
        return SourceSchema(name=name, supports_incremental=False, supports_append=False, **kwargs)

    def test_persists_columns_foreign_keys_and_source_fields(self) -> None:
        source = self._source()
        schema = self._schema(source)

        result = reconcile_source_schema_metadata(
            source,
            [
                self._source_schema(
                    columns=[("id", "Int64", False), ("ts", "DateTime", True)],
                    foreign_keys=[("author_id", "users", "id")],
                    source_catalog="default",
                    source_schema="public",
                    source_table_name="messages",
                )
            ],
            self.team.pk,
        )

        assert result == []
        schema.refresh_from_db()
        metadata = schema.sync_type_config["schema_metadata"]
        assert metadata["columns"] == [
            {"name": "id", "data_type": "Int64", "is_nullable": False},
            {"name": "ts", "data_type": "DateTime", "is_nullable": True},
        ]
        assert metadata["foreign_keys"] == [{"column": "author_id", "target_table": "users", "target_column": "id"}]
        assert metadata["source_catalog"] == "default"
        assert metadata["source_schema"] == "public"
        assert metadata["source_table_name"] == "messages"

    def test_merges_into_existing_sync_type_config(self) -> None:
        source = self._source()
        schema = self._schema(source, sync_type_config={"incremental_field": "ts", "chunk_size_override": 5})

        reconcile_source_schema_metadata(source, [self._source_schema(columns=[("id", "Int64", False)])], self.team.pk)

        schema.refresh_from_db()
        assert schema.sync_type_config["incremental_field"] == "ts"
        assert schema.sync_type_config["chunk_size_override"] == 5
        assert "schema_metadata" in schema.sync_type_config

    def test_prunes_enabled_columns_missing_from_source(self) -> None:
        source = self._source()
        schema = self._schema(source, enabled_columns=["id", "dropped"])

        reconcile_source_schema_metadata(
            source, [self._source_schema(columns=[("id", "Int64", False), ("ts", "DateTime", True)])], self.team.pk
        )

        schema.refresh_from_db()
        assert schema.enabled_columns == ["id"]

    def test_keeps_enabled_columns_when_all_present(self) -> None:
        source = self._source()
        schema = self._schema(source, enabled_columns=["id", "ts"])

        reconcile_source_schema_metadata(
            source, [self._source_schema(columns=[("id", "Int64", False), ("ts", "DateTime", True)])], self.team.pk
        )

        schema.refresh_from_db()
        assert schema.enabled_columns == ["id", "ts"]

    def test_skips_schema_without_a_matching_source_schema(self) -> None:
        source = self._source()
        schema = self._schema(source, name="messages")

        reconcile_source_schema_metadata(
            source, [self._source_schema(name="other", columns=[("id", "Int64", False)])], self.team.pk
        )

        schema.refresh_from_db()
        assert schema.schema_metadata is None

    def test_does_not_touch_schemas_on_a_different_source(self) -> None:
        source = self._source()
        other_source = self._source()
        schema = self._schema(other_source, name="messages")

        reconcile_source_schema_metadata(
            source, [self._source_schema(name="messages", columns=[("id", "Int64", False)])], self.team.pk
        )

        schema.refresh_from_db()
        assert schema.schema_metadata is None
