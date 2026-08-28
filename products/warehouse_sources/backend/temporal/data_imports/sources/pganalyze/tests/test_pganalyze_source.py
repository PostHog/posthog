from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pganalyze import (
    PgAnalyzeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pganalyze.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pganalyze.source import PgAnalyzeSource


class TestPgAnalyzeSource:
    def setup_method(self):
        self.source = PgAnalyzeSource()
        self.team_id = 123
        self.config = PgAnalyzeSourceConfig(
            api_key="pganalyze_test_token",
            organization_slug="acme",
            api_url=None,
        )

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        schema_names = {schema.name for schema in schemas}
        assert schema_names == set(ENDPOINTS)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["issues"])

        assert len(schemas) == 1
        assert schemas[0].name == "issues"

    def test_servers_schema_does_not_support_incremental(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["servers"])

        assert len(schemas) == 1
        assert schemas[0].supports_incremental is False

    def test_issues_schema_supports_incremental(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["issues"])

        assert len(schemas) == 1
        assert schemas[0].supports_incremental is True
