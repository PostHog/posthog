from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.railway import (
    RailwaySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.railway.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.railway.source import RailwaySource


class TestRailwaySource:
    def setup_method(self):
        self.source = RailwaySource()
        self.team_id = 123
        self.config = RailwaySourceConfig(api_token="railway-token")

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Railway has no server-side time filters; only deployments (newest-first, watermark-stop)
        # can sync incrementally.
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        assert incremental == {"deployments"}

    def test_deployments_schema_incremental_settings(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        deployments = schemas["deployments"]
        assert [f["field"] for f in deployments.incremental_fields] == ["createdAt"]
        # Deployment rows mutate (status) — merge-only, with a lookback so recent statuses settle.
        assert deployments.supports_append is False
        assert deployments.default_incremental_lookback_seconds == 86400
