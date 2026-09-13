import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wrike import WrikeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.source import WrikeSource


class TestWrikeSource:
    def setup_method(self):
        self.source = WrikeSource()
        self.team_id = 123
        self.config = WrikeSourceConfig(access_token="token", host="www.wrike.com")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://www.wrike.com/api/v4/tasks",
            "403 Client Error: Forbidden for url: https://www.wrike.com/api/v4/contacts",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://www.wrike.com/api/v4/tasks",
            "500 Server Error for url: https://www.wrike.com/api/v4/tasks",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_covers_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_get_schemas_are_full_refresh_only(self):
        # Wrike ships full refresh only until the server-side updatedDate filter is verified.
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["tasks"])
        assert len(schemas) == 1
        assert schemas[0].name == "tasks"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []
