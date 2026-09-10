import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.breezometer.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.breezometer.source import BreezometerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.breezometer import (
    BreezometerSourceConfig,
)


class TestBreezometerSource:
    def setup_method(self):
        self.source = BreezometerSource()
        self.team_id = 123
        self.config = BreezometerSourceConfig(api_key="test-key", locations="51.5,-0.12,London")

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O — must opt in so public docs render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_get_schemas_supports_append_not_incremental(self, endpoint):
        # No endpoint exposes a server-side change cursor, so none is truly incremental;
        # all support append so users can accumulate snapshots over time.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is True
        assert [f["field"] for f in schemas[endpoint].incremental_fields] == ["dt_iso"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["pollen_forecast"])

        assert [schema.name for schema in schemas] == ["pollen_forecast"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_documented_tables_render_without_credentials(self):
        # Exercises the public-docs path: a credential-free placeholder config must list every table.
        tables = self.source.get_documented_tables()

        assert {table["name"] for table in tables} == set(ENDPOINTS)
