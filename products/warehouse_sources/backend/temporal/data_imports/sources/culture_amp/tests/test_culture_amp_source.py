import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.source import CultureAmpSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cultureamp import (
    CultureAmpSourceConfig,
)


class TestCultureAmpSource:
    def setup_method(self):
        self.source = CultureAmpSource()
        self.team_id = 123
        self.config = CultureAmpSourceConfig(client_id="cid", client_secret="sec", account_id="entity-1")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "400 Client Error: Bad Request for url: https://api.cultureamp.com/v1/oauth2/token",
            "401 Client Error: Unauthorized for url: https://api.cultureamp.com/v1/oauth2/token",
            "403 Client Error: Forbidden for url: https://api.cultureamp.com/v1/employees",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://api.cultureamp.com/v1/employees",
            # Mid-sync 401s on data endpoints are handled by token re-mint.
            "401 Client Error: Unauthorized for url: https://api.cultureamp.com/v1/employees",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Only the performance streams expose the server-side after_date filter.
        incremental = {name for name, schema in schemas.items() if schema.supports_incremental}
        assert incremental == {"performance_cycles", "manager_reviews"}
        assert schemas["manager_reviews"].incremental_fields == INCREMENTAL_FIELDS["manager_reviews"]
        assert [f["field"] for f in schemas["performance_cycles"].incremental_fields] == ["processedAt"]
        assert schemas["employees"].incremental_fields == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.culture_amp.source.validate_culture_amp_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert "employees read permission" in (error_message or "")
        mock_validate.assert_called_once_with("cid", "sec", "entity-1")
