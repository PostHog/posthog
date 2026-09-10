import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pypi import PyPISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pypi.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pypi.source import PyPISource


class TestPyPISource:
    def setup_method(self):
        self.source = PyPISource()
        self.team_id = 123
        self.config = PyPISourceConfig(packages="requests\ndjango")

    def test_get_schemas_lists_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_get_schemas_full_refresh_only(self, endpoint):
        # PyPI exposes no server-side timestamp filter, so no stream is incremental or append.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["releases"])

        assert [schema.name for schema in schemas] == ["releases"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nonexistent"]) == []

    def test_no_non_retryable_errors(self):
        # Unauthenticated API: there are no credential errors to permanently fail on.
        assert self.source.get_non_retryable_errors() == {}

    def test_lists_tables_without_credentials(self):
        # Static endpoint catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True
        assert len(self.source.get_documented_tables()) == len(ENDPOINTS)
