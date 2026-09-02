import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pendo import PendoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.source import PendoSource


class TestPendoSource:
    def setup_method(self):
        self.source = PendoSource()
        self.team_id = 123
        self.config = PendoSourceConfig(integration_key="integration-key", region="eu")

    def test_get_schemas_are_all_full_refresh(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(schema.supports_incremental is False for schema in schemas)
        assert all(schema.supports_append is False for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["visitors"])
        assert len(schemas) == 1
        assert schemas[0].name == "visitors"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://app.pendo.io/api/v1/page",
            "403 Client Error: Forbidden for url: https://app.pendo.io/api/v1/aggregation",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://app.pendo.io/api/v1/page",
            "500 Server Error for url: https://app.pendo.io/api/v1/aggregation",
        ],
    )
    def test_non_retryable_errors_do_not_match_retryable(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)
