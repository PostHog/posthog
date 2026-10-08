import pytest
from unittest import mock

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
