import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.clickup.source import ClickUpSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clickup import (
    ClickUpSourceConfig,
)


class TestClickUpSource:
    def setup_method(self) -> None:
        self.source = ClickUpSource()
        self.team_id = 123
        self.config = ClickUpSourceConfig(api_key="pk_token", workspace_id="9008123456")

    def test_workspace_id_is_a_connection_host_field(self) -> None:
        # Changing the workspace the token targets must re-require the token.
        assert self.source.connection_host_fields == ["workspace_id"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.clickup.com/api/v2/team",
            "403 Client Error: Forbidden for url: https://api.clickup.com/api/v2/team/9/task",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.clickup.com/api/v2/team",
        ],
    )
    def test_non_retryable_errors_ignore_unrelated(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only tasks expose ClickUp's server-side date_updated_gt filter.
        assert incremental == {"tasks"}
        assert all(schema.supports_append is False for schema in schemas)
