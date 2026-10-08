from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lingodev import (
    LingoDevSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lingo_dev.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.lingo_dev.source import LingoDevSource


class TestLingoDevSource:
    def setup_method(self):
        self.source = LingoDevSource()
        self.team_id = 123
        self.config = LingoDevSourceConfig(api_key="test-key")

    @parameterized.expand(
        [
            ("stripe", "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers"),
            ("clerk", "401 Client Error: Unauthorized for url: https://api.clerk.com/v1/users"),
        ]
    )
    def test_non_retryable_errors_does_not_match_other_vendors(self, _name, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_filtered_by_names(self):
        first_endpoint = next(iter(ENDPOINTS))
        schemas = self.source.get_schemas(self.config, self.team_id, names=[first_endpoint])

        assert len(schemas) == 1
        assert schemas[0].name == first_endpoint
