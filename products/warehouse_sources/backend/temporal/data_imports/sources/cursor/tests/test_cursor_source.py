from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceFieldInputConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.source import CursorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cursor import CursorSourceConfig


class TestCursorSource:
    def setup_method(self):
        self.source = CursorSource()
        self.config = CursorSourceConfig(api_key="key_test")
        self.team_id = 123

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name == SchemaExternalDataSourceType.CURSOR
        assert config.label == "Cursor"
        field = config.fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert len(config.fields) == 1
        assert field.name == "api_key"
        assert field.required is True
        assert field.secret is True
        # The docs slug is derived from docsUrl; a mismatch 404s the public doc.
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/cursor"

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert [s.name for s in schemas] == ["members", "daily_usage", "usage_events", "spend"]
        assert all(s.should_sync_default for s in schemas)

    @parameterized.expand(
        [
            ("members", False, None),
            ("daily_usage", True, "date"),
            ("usage_events", True, "timestamp"),
            ("spend", False, None),
        ]
    )
    def test_get_schemas_incremental_support(self, endpoint, supports_incremental, incremental_field):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        schema = schemas[endpoint]

        assert schema.supports_incremental is supports_incremental
        assert schema.supports_append is supports_incremental
        if incremental_field:
            assert [f["field"] for f in schema.incremental_fields] == [incremental_field]
        else:
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["members", "spend"])

        assert [s.name for s in schemas] == ["members", "spend"]

    def test_get_documented_tables_lists_endpoints_without_credentials(self):
        # lists_tables_without_credentials=True drives the public docs' Supported tables section.
        tables = self.source.get_documented_tables()

        assert [t["name"] for t in tables] == ["members", "daily_usage", "usage_events", "spend"]
        assert all(t["description"] for t in tables)

    @parameterized.expand([(True, (True, None)), (False, (False, "Invalid Cursor Admin API key"))])
    def test_validate_credentials(self, valid, expected):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cursor.source.validate_cursor_credentials",
            return_value=valid,
        ):
            assert self.source.validate_credentials(self.config, self.team_id) == expected
