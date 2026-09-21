import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gridly import GridlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.source import GridlySource

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gridly.source"


class TestGridlySource:
    def setup_method(self):
        self.source = GridlySource()
        self.team_id = 123
        self.config = GridlySourceConfig(api_key="key", view_id="view")

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog (no I/O), so the source opts into public-docs table listing.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.gridly.com/v1/views/abc",
            "403 Client Error: Forbidden for url: https://api.gridly.com/v1/views/abc/records",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.gridly.com/v1/views/abc/records",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)
        assert all(schema.detected_primary_keys == ["id"] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["records"])
        assert [s.name for s in schemas] == ["records"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []
