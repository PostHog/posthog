import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_ads.settings import (
    AMAZON_ADS_ENDPOINTS,
    ENDPOINTS,
)
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

    def test_report_schemas_carry_a_cursor_and_entity_schemas_do_not(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name, config in AMAZON_ADS_ENDPOINTS.items():
            schema = schemas[name]
            assert not schema.supports_append
            if config.report is None:
                assert not schema.supports_incremental
                assert schema.incremental_fields == []
                assert schema.default_incremental_lookback_seconds is None
            else:
                assert schema.supports_incremental
                # Amazon only lets a report be windowed on `date`, and it restates recent days as
                # attribution lands, so the schema has to re-read a trailing window every run.
                assert [field["field"] for field in schema.incremental_fields] == ["date"]
                assert schema.default_incremental_lookback_seconds

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
