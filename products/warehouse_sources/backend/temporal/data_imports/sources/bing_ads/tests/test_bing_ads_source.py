import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.source import BingAdsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bingads import (
    BingAdsSourceConfig,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


class TestBingAdsSource:
    """Test suite for BingAdsSource configuration."""

    def setup_method(self):
        """Set up test fixtures."""
        self.source = BingAdsSource()
        self.team_id = 123
        self.valid_config = BingAdsSourceConfig(
            account_id="12345",
            bing_ads_integration_id=1,
        )

    @pytest.mark.parametrize(
        "account_id,integration_id,expected_error_fragment",
        [
            ("", 1, "Account ID and Bing Ads integration are required"),
            ("12345", 0, "Account ID and Bing Ads integration are required"),
            ("ABC123XYZ", 1, "Invalid Account ID"),
        ],
    )
    def test_validate_credentials_invalid_input(self, account_id, integration_id, expected_error_fragment):
        """Validation fails on bad input before ever touching the OAuth integration."""
        config = BingAdsSourceConfig(account_id=account_id, bing_ads_integration_id=integration_id)

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error is not None
        assert expected_error_fragment in error

    @mock.patch.object(BingAdsSource, "get_oauth_integration")
    def test_validate_credentials_success(self, mock_get_oauth):
        mock_integration = mock.MagicMock()
        mock_get_oauth.return_value = mock_integration

        is_valid, error = self.source.validate_credentials(self.valid_config, self.team_id)

        assert is_valid is True
        assert error is None
        mock_get_oauth.assert_called_once_with(1, self.team_id)

    @pytest.mark.parametrize(
        "side_effect,expected_error_fragment,expect_capture_called",
        [
            # A deleted/disconnected integration is an expected user state — surface a clean
            # "reconnect" message and do NOT report it to error tracking.
            (ValueError("Integration not found: 162559"), "Bing Ads integration not found", False),
            # Anything else is genuinely unexpected and must still be captured.
            (Exception("OAuth error"), "Failed to validate Bing Ads credentials", True),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.source.capture_exception")
    @mock.patch.object(BingAdsSource, "get_oauth_integration")
    def test_validate_credentials_oauth_failures(
        self, mock_get_oauth, mock_capture, side_effect, expected_error_fragment, expect_capture_called
    ):
        """Validation distinguishes an expected missing integration from a genuine error."""
        mock_get_oauth.side_effect = side_effect

        is_valid, error = self.source.validate_credentials(self.valid_config, self.team_id)

        assert is_valid is False
        assert error is not None
        assert expected_error_fragment in error
        assert mock_capture.called is expect_capture_called

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.valid_config, self.team_id)

        assert len(schemas) > 0

        schema_names = [s.name for s in schemas]
        assert "campaigns" in schema_names
        assert "campaign_performance_report" in schema_names
        assert "ad_group_performance_report" in schema_names
        assert "ad_performance_report" in schema_names

        campaigns_schema = next(s for s in schemas if s.name == "campaigns")
        assert campaigns_schema.supports_incremental is False
        assert campaigns_schema.supports_append is False
        assert len(campaigns_schema.incremental_fields) == 0

        report_schema = next(s for s in schemas if s.name == "campaign_performance_report")
        assert report_schema.supports_incremental is True
        assert report_schema.supports_append is True
        assert len(report_schema.incremental_fields) == 1
        assert report_schema.incremental_fields[0]["field"] == "TimePeriod"
        assert report_schema.incremental_fields[0]["field_type"] == IncrementalFieldType.Date

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.source.bing_ads_source")
    @mock.patch.object(BingAdsSource, "get_oauth_integration")
    def test_source_for_pipeline_campaigns(self, mock_get_oauth, mock_bing_ads_source):
        mock_integration = mock.MagicMock()
        mock_integration.access_token = "test_access_token"
        mock_integration.refresh_token = "test_refresh_token"
        mock_get_oauth.return_value = mock_integration

        mock_source_response = mock.MagicMock()
        mock_bing_ads_source.return_value = mock_source_response

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "test-job-id"
        inputs.schema_name = "campaigns"
        inputs.should_use_incremental_field = False
        inputs.incremental_field = None
        inputs.incremental_field_type = None
        inputs.db_incremental_field_last_value = None

        resumable_manager = mock.MagicMock(spec=ResumableSourceManager)
        result = self.source.source_for_pipeline(self.valid_config, resumable_manager, inputs)

        assert result == mock_source_response
        mock_bing_ads_source.assert_called_once_with(
            account_id="12345",
            resource_name="campaigns",
            access_token="test_access_token",
            refresh_token="test_refresh_token",
            resumable_source_manager=resumable_manager,
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.source.bing_ads_source")
    @mock.patch.object(BingAdsSource, "get_oauth_integration")
    def test_source_for_pipeline_report_incremental(self, mock_get_oauth, mock_bing_ads_source):
        mock_integration = mock.MagicMock()
        mock_integration.access_token = "test_access_token"
        mock_integration.refresh_token = "test_refresh_token"
        mock_get_oauth.return_value = mock_integration

        mock_source_response = mock.MagicMock()
        mock_bing_ads_source.return_value = mock_source_response

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "test-job-id"
        inputs.schema_name = "campaign_performance_report"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "TimePeriod"
        inputs.incremental_field_type = IncrementalFieldType.Date
        inputs.db_incremental_field_last_value = "2024-01-01"

        resumable_manager = mock.MagicMock(spec=ResumableSourceManager)
        result = self.source.source_for_pipeline(self.valid_config, resumable_manager, inputs)

        assert result == mock_source_response
        mock_bing_ads_source.assert_called_once_with(
            account_id="12345",
            resource_name="campaign_performance_report",
            access_token="test_access_token",
            refresh_token="test_refresh_token",
            resumable_source_manager=resumable_manager,
            should_use_incremental_field=True,
            incremental_field="TimePeriod",
            incremental_field_type=IncrementalFieldType.Date,
            db_incremental_field_last_value="2024-01-01",
        )

    @mock.patch.object(BingAdsSource, "get_oauth_integration")
    def test_source_for_pipeline_missing_access_token(self, mock_get_oauth):
        mock_integration = mock.MagicMock()
        mock_integration.access_token = None
        mock_integration.refresh_token = "test_refresh_token"
        mock_get_oauth.return_value = mock_integration

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "test-job-id"
        inputs.schema_name = "campaigns"

        resumable_manager = mock.MagicMock(spec=ResumableSourceManager)
        with pytest.raises(ValueError, match="Bing Ads access token not found for job test-job-id"):
            self.source.source_for_pipeline(self.valid_config, resumable_manager, inputs)

    @mock.patch.object(BingAdsSource, "get_oauth_integration")
    def test_source_for_pipeline_missing_refresh_token(self, mock_get_oauth):
        mock_integration = mock.MagicMock()
        mock_integration.access_token = "test_access_token"
        mock_integration.refresh_token = None
        mock_get_oauth.return_value = mock_integration

        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "test-job-id"
        inputs.schema_name = "campaigns"

        resumable_manager = mock.MagicMock(spec=ResumableSourceManager)
        with pytest.raises(ValueError, match="Bing Ads refresh token not found for job test-job-id"):
            self.source.source_for_pipeline(self.valid_config, resumable_manager, inputs)

    def test_aadsts650052_message_wins_over_generic_auth_wrappers(self):
        # The real error string contains "OAuthTokenRequestException", "invalid_client", AND "AADSTS650052"
        # as substrings. handle_non_retryable in external_data_job.py picks the first matching dict entry,
        # so AADSTS650052 must come before BOTH generic wrappers — otherwise the user sees the
        # "reconnect your integration" toast instead of the service-principal guidance, and reconnecting
        # cannot fix it (only an org admin granting tenant consent can).
        non_retryable_errors = self.source.get_non_retryable_errors()
        keys = list(non_retryable_errors.keys())

        aadsts_index = keys.index("AADSTS650052")
        assert aadsts_index < keys.index("OAuthTokenRequestException")
        assert aadsts_index < keys.index("invalid_client")

        error_message = (
            "Failed to fetch customer ID: OAuthTokenRequestException: invalid_client AADSTS650052: "
            "The app is trying to access a service that your organization lacks a service principal for."
        )
        friendly_errors = [msg for pattern, msg in non_retryable_errors.items() if pattern in error_message]
        assert friendly_errors[0] is not None
        assert "AADSTS650052" in friendly_errors[0]
        assert "service principal" in friendly_errors[0]

    def test_aadsts7000215_is_internal_config_not_customer_actionable(self):
        # AADSTS7000215 means PostHog's own app secret is invalid/expired. The message also contains
        # "OAuthTokenRequestException" and "invalid_client", both of which map to the customer-facing
        # "reconnect your integration" toast — so AADSTS7000215 must precede them and resolve to None,
        # keeping the misleading toast off an error only a PostHog config change can fix.
        non_retryable_errors = self.source.get_non_retryable_errors()
        keys = list(non_retryable_errors.keys())

        aadsts_index = keys.index("AADSTS7000215")
        assert aadsts_index < keys.index("OAuthTokenRequestException")
        assert aadsts_index < keys.index("invalid_client")

        error_message = (
            "Failed to fetch customer ID: OAuthTokenRequestException: error_code: invalid_client, "
            "error_description: AADSTS7000215: Invalid client secret provided."
        )
        friendly_errors = [msg for pattern, msg in non_retryable_errors.items() if pattern in error_message]
        assert friendly_errors[0] is None

    def test_invalid_client_data_maps_to_account_guidance(self):
        # The dominant cause is a wrong/inaccessible Account ID (auth has already succeeded by this point),
        # so the toast must point at the Account ID rather than telling the user to reconnect OAuth.
        non_retryable_errors = self.source.get_non_retryable_errors()
        error_message = (
            "Server raised fault: 'Invalid client data. Check the SOAP fault details for more "
            "information. TrackingId: 9471598f-2992-4c98-9d96-cbe84a0ddb47.'"
        )
        friendly_errors = [msg for pattern, msg in non_retryable_errors.items() if pattern in error_message]

        assert friendly_errors[0] is not None
        assert "Account ID" in friendly_errors[0]

    def test_transient_bad_request_is_retryable_not_disabling(self):
        # A bare transport-level HTTP 400 on a Bing SOAP call (no coded WebFault) is a transient edge
        # rejection: it must be recognised as retryable (kept out of error tracking) and must NOT match
        # any non-retryable pattern, or a transient blip would disable the schema.
        error_message = "Failed to generate ad_performance_report report: Exception: (400, 'Bad Request')"

        # Assert through the same case-insensitive matcher production classification uses.
        assert error_message_matches(error_message, self.source.get_retryable_errors())
        assert not error_message_matches(error_message, self.source.get_non_retryable_errors())
