from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.windmill import (
    WindmillSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.source import WindmillSource

BASE_URL = "https://app.windmill.dev"
WORKSPACE = "my-workspace"


class TestWindmillSource:
    def setup_method(self):
        self.source = WindmillSource()
        self.team_id = 123
        self.config = WindmillSourceConfig(host=BASE_URL, workspace=WORKSPACE, api_token="token")

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only completed_jobs exposes a genuine server-side timestamp filter.
        assert incremental == {"completed_jobs"}
