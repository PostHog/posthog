from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.northflank import (
    NorthflankSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.northflank.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.northflank.source import NorthflankSource


class TestNorthflankSource:
    def setup_method(self):
        self.source = NorthflankSource()
        self.team_id = 123
        self.config = NorthflankSourceConfig(api_token="nf-token")

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.northflank.com/v1/projects?per_page=1",),
            ("403 Client Error: Forbidden for url: https://api.northflank.com/v1/projects/abc/services",),
        ]
    )
    def test_non_retryable_errors_match_permanent_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("429 Client Error: Too Many Requests for url: https://api.northflank.com/v1/projects",),
            ("500 Server Error for url: https://api.northflank.com/v1/projects",),
            ("401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",),
        ]
    )
    def test_non_retryable_errors_ignore_transient_and_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_no_endpoint_advertises_incremental(self, endpoint):
        # Northflank exposes no server-side timestamp filter, so every table is full refresh.
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id) if s.name == endpoint)
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["services"])
        assert [s.name for s in schemas] == ["services"]
