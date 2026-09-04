import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.source import AmazonAdsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amazonads import (
    AmazonAdsSourceConfig,
)


class TestAmazonAdsSource:
    def setup_method(self):
        self.source = AmazonAdsSource()
        self.team_id = 123
        self.config = AmazonAdsSourceConfig(region="na", client_id="cid", client_secret="sec", refresh_token="rt")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "400 Client Error: Bad Request for url: https://api.amazon.com/auth/o2/token",
            "401 Client Error: Unauthorized for url: https://api.amazon.com/auth/o2/token",
            "403 Client Error: Forbidden for url: https://advertising-api.amazon.com/v2/profiles",
            "403 Client Error: Forbidden for url: https://advertising-api-eu.amazon.com/sp/campaigns/list",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://advertising-api.amazon.com/v2/profiles",
            # Mid-sync 401s on the API host are handled by token re-mint.
            "401 Client Error: Unauthorized for url: https://advertising-api.amazon.com/v2/profiles",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["sp_campaigns"])
        assert len(schemas) == 1
        assert schemas[0].name == "sp_campaigns"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Amazon Ads credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.source.validate_amazon_ads_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("na", "cid", "sec", "rt")
