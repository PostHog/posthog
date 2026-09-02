import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.dixa.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.dixa.source import DixaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dixa import DixaSourceConfig


class TestDixaSource:
    def setup_method(self):
        self.source = DixaSource()
        self.team_id = 123
        self.config = DixaSourceConfig(api_token="api-token")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://dev.dixa.io/v1/agents",
            "401 Client Error: Unauthorized for url: https://exports.dixa.io/v1/conversation_export",
            "403 Client Error: Forbidden for url: https://exports.dixa.io/v1/conversation_export",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://dev.dixa.io/v1/agents",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only the exports surface has server-side updated_after filtering.
        assert incremental == {"conversations"}
