from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.source import CircleCISource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.circleci import (
    CircleCISourceConfig,
)


class TestCircleCISource:
    def setup_method(self):
        self.source = CircleCISource()
        self.team_id = 123
        self.config = CircleCISourceConfig(api_token="circle-token", org_slug="gh/posthog")

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_no_endpoint_advertises_incremental(self, endpoint):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        # No CircleCI v2 list endpoint has a server-side timestamp filter, so all are full refresh.
        assert schemas[endpoint].supports_incremental is False
        assert schemas[endpoint].supports_append is False
        assert schemas[endpoint].incremental_fields == []
        assert INCREMENTAL_FIELDS.get(endpoint) is None
