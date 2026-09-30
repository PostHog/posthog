import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartlead import (
    SmartleadSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlead.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlead.source import SmartleadSource

VALIDATE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.smartlead.source.validate_smartlead_credentials"
)


class TestSmartleadSource:
    def setup_method(self):
        self.source = SmartleadSource()
        self.team_id = 123
        self.config = SmartleadSourceConfig(api_key="key")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://server.smartlead.ai/api/v1/campaigns/ | api error: Invalid API Key",
            "403 Client Error: Forbidden for url: https://server.smartlead.ai/api/v1/client/",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://server.smartlead.ai/api/v1/campaigns/",
            "500 Server Error: Internal Server Error for url: https://server.smartlead.ai/api/v1/campaigns/",
            "HTTPSConnectionPool(host='server.smartlead.ai', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_every_endpoint_is_full_refresh_only(self):
        # Smartlead's documented time filters (`created_at_gt`, `sent_time_start_date`) are
        # unverified against a live account and the list ordering is undocumented, so no schema
        # may advertise incremental sync until that changes (see settings.py).
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.supports_append is False

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Smartlead API key"),
            ((False, 403), False, "Could not connect to Smartlead with the provided API key"),
            ((False, None), False, "Could not connect to Smartlead with the provided API key"),
        ],
    )
    @mock.patch(VALIDATE_PATCH)
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key")
