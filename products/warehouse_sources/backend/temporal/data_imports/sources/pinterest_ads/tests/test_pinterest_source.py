import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pinterestads import (
    PinterestAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.source import PinterestAdsSource


class TestPinterestAdsSource:
    def setup_method(self):
        self.source = PinterestAdsSource()
        self.team_id = 123
        self.config = PinterestAdsSourceConfig(pinterest_ads_integration_id=456, ad_account_id="789")

    def test_validate_credentials_missing_account_id(self):
        invalid_config = PinterestAdsSourceConfig(pinterest_ads_integration_id=456, ad_account_id="")
        is_valid, error_message = self.source.validate_credentials(invalid_config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "Ad Account ID and Pinterest Ads integration are required" in error_message

    def test_validate_credentials_missing_integration_id(self):
        invalid_config = PinterestAdsSourceConfig(pinterest_ads_integration_id=0, ad_account_id="789")
        is_valid, error_message = self.source.validate_credentials(invalid_config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "Ad Account ID and Pinterest Ads integration are required" in error_message

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.source.PinterestAdsSource.get_oauth_integration"
    )
    def test_validate_credentials_success(self, mock_get_oauth):
        mock_get_oauth.return_value = mock.MagicMock()

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.source.PinterestAdsSource.get_oauth_integration"
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.source.capture_exception"
    )
    def test_validate_credentials_integration_error(self, mock_capture, mock_get_oauth):
        mock_get_oauth.side_effect = Exception("Integration not found")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "Failed to validate Pinterest Ads credentials" in error_message
        mock_capture.assert_called_once()

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        expected_endpoints = [
            "campaigns",
            "ad_groups",
            "ads",
            "ad_accounts",
            "audiences",
            "conversion_tags",
            "keywords",
            "campaign_analytics",
            "ad_group_analytics",
            "ad_analytics",
            "campaign_targeting_analytics",
            "ad_group_targeting_analytics",
            "ad_targeting_analytics",
        ]
        assert len(schemas) == len(expected_endpoints)

        schema_names = [schema.name for schema in schemas]
        for endpoint in expected_endpoints:
            assert endpoint in schema_names

    @pytest.mark.parametrize(
        "endpoint,should_sync_default",
        [
            ("campaigns", True),
            ("campaign_analytics", True),
            ("ad_accounts", True),
            ("audiences", True),
            ("conversion_tags", True),
            ("keywords", True),
            # Breakdown tables fan out over every entity, day and targeting type, so a customer has
            # to opt into them rather than have them switched on by the schema picker.
            ("campaign_targeting_analytics", False),
            ("ad_group_targeting_analytics", False),
            ("ad_targeting_analytics", False),
        ],
    )
    def test_expensive_breakdown_tables_are_off_by_default(self, endpoint, should_sync_default):
        schemas = self.source.get_schemas(self.config, self.team_id, names=[endpoint])

        assert [schema.should_sync_default for schema in schemas] == [should_sync_default]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.source.PinterestAdsSource.get_oauth_integration"
    )
    def test_source_for_pipeline_success(self, mock_get_oauth):
        mock_integration = mock.MagicMock()
        mock_integration.access_token = "test_token"
        mock_get_oauth.return_value = mock_integration

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.source.pinterest_ads_source"
        ) as mock_pipeline:
            mock_response = mock.MagicMock()
            mock_pipeline.return_value = mock_response

            inputs = mock.MagicMock()
            inputs.team_id = self.team_id
            inputs.job_id = "test_job"
            inputs.schema_name = "campaigns"
            inputs.should_use_incremental_field = False
            inputs.db_incremental_field_last_value = None

            resumable_manager = mock.MagicMock()
            result = self.source.source_for_pipeline(self.config, resumable_manager, inputs)

            assert result == mock_response
            mock_pipeline.assert_called_once_with(
                ad_account_id=self.config.ad_account_id,
                endpoint="campaigns",
                access_token="test_token",
                resumable_source_manager=resumable_manager,
                source_logger=inputs.logger,
                should_use_incremental_field=False,
                db_incremental_field_last_value=None,
            )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.source.PinterestAdsSource.get_oauth_integration"
    )
    def test_source_for_pipeline_no_access_token(self, mock_get_oauth):
        mock_integration = mock.MagicMock()
        mock_integration.access_token = None
        mock_get_oauth.return_value = mock_integration

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "test_job"
        inputs.schema_name = "campaigns"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = None

        with pytest.raises(ValueError, match="Pinterest Ads access token not found for job test_job"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

    @pytest.mark.parametrize(
        "transport_error",
        [requests.ConnectionError("connection reset"), requests.ReadTimeout("read timed out")],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.source.list_ad_accounts"
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.source.build_session")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pinterest_ads.source.OauthIntegration"
    )
    @mock.patch.object(PinterestAdsSource, "get_oauth_integration")
    def test_get_oauth_accounts_maps_transport_failure_to_listing_error(
        self, mock_get_oauth, mock_oauth_integration, mock_build_session, mock_list_ad_accounts, transport_error
    ):
        # A connection error / read timeout survives the retry policy and reaches the picker as a
        # RequestException (not an HTTPError); it must become an actionable transient error, not a 500.
        integration = mock.MagicMock()
        integration.errors = ""
        integration.access_token = "token"
        mock_get_oauth.return_value = integration
        mock_oauth_integration.return_value.access_token_expired.return_value = False
        mock_list_ad_accounts.side_effect = transport_error

        with pytest.raises(IntegrationAccountListingError, match="Pinterest is having trouble responding"):
            self.source.get_oauth_accounts(456, self.team_id)
