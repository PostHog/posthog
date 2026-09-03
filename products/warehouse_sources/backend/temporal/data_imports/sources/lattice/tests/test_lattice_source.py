import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lattice import (
    LatticeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.source import LatticeSource


class TestLatticeSource:
    def setup_method(self):
        self.source = LatticeSource()
        self.team_id = 123
        self.config = LatticeSourceConfig(region="us", api_key="api-key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.latticehq.com/v1/users?limit=100",
            "401 Client Error: Unauthorized for url: https://api.emea.latticehq.com/v1/goals",
            "403 Client Error: Forbidden for url: https://api.latticehq.com/v1/feedbacks",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.latticehq.com/v1/users",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # No Lattice list endpoint has a server-side timestamp filter.
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)
