import pytest
from unittest import mock

from posthog.schema import SourceFieldOauthAccountSelectConfig, SourceFieldOauthConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.source import BingAdsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.bing_ads.utils import BingAdsResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BingAdsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType


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

    def test_source_type(self):
        """Test source type is correctly set."""
        assert self.source.source_type == ExternalDataSourceType.BINGADS

    def test_get_source_config(self):
        """Test source configuration is properly structured."""
        config = self.source.get_source_config

        assert config.name.value == "BingAds"
        assert config.label == "Bing Ads"
        assert config.releaseStatus == "beta"
        assert config.iconPath == "/static/services/bing-ads.svg"
        assert len(config.fields) == 2

        oauth_field = config.fields[0]
        assert isinstance(oauth_field, SourceFieldOauthConfig)
        assert oauth_field.name == "bing_ads_integration_id"
        assert oauth_field.required is True
        assert oauth_field.kind == "bing-ads"

        account_id_field = config.fields[1]
        assert isinstance(account_id_field, SourceFieldOauthAccountSelectConfig)
        assert account_id_field.name == "account_id"
        assert account_id_field.required is True
        assert account_id_field.integrationField == "bing_ads_integration_id"
        assert account_id_field.integrationKind == "bing-ads"

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
        """Test successful credential validation."""
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
        """Test getting available schemas."""
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
        """Test creating source for pipeline with campaigns."""
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
        """Test creating source for pipeline with incremental report."""
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
        """Test source_for_pipeline raises error when access token is missing."""
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
        """Test source_for_pipeline raises error when refresh token is missing."""
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

    @pytest.mark.parametrize(
        "pattern,raised_message",
        [
            # Auth-specific substrings — wrapped by BingAdsClient.get_customer_id as
            # `ValueError("Failed to fetch customer ID: <ExcType>: <msg>")`, so the substring
            # must appear inside that combined message.
            (
                "OAuthTokenRequestException",
                "Failed to fetch customer ID: OAuthTokenRequestException: invalid_grant ...",
            ),
            (
                "invalid_grant",
                "Failed to fetch customer ID: OAuthTokenRequestException: invalid_grant ...",
            ),
            (
                "AuthenticationTokenExpired",
                "Failed to fetch customer ID: WebFault: ... AuthenticationTokenExpired ...",
            ),
            (
                "InvalidCredentials",
                "Failed to fetch customer ID: WebFault: ... InvalidCredentials ...",
            ),
            # Generic SOAP fault returned by GetUser when the connected account's credentials/identity
            # can't be used. GetUser takes no request params, so this is never our bug — stop retrying.
            (
                "Invalid client data",
                "Failed to fetch customer ID: WebFault: Server raised fault: 'Invalid client data. "
                "Check the SOAP fault details for more information. TrackingId: abc-123.'",
            ),
            # Specific Azure AD code — tenant missing service principal for the Microsoft Advertising API.
            (
                "AADSTS650052",
                "Failed to fetch customer ID: OAuthTokenRequestException: invalid_client AADSTS650052: "
                "The app is trying to access a service that your organization lacks a service principal for.",
            ),
            # Bing rejects the request as invalid after auth succeeds (e.g. wrong/inaccessible Account ID).
            # The SDK raises suds.WebFault whose str() embeds a volatile TrackingId — match the stable phrase.
            (
                "Invalid client data",
                "Server raised fault: 'Invalid client data. Check the SOAP fault details for more "
                "information. TrackingId: 9471598f-2992-4c98-9d96-cbe84a0ddb47.'",
            ),
            # Integration deleted/disconnected — OAuthMixin.get_oauth_integration raises
            # `ValueError("Integration not found: <id>")`; match only the volatile-id-free prefix.
            ("Integration not found", "Integration not found: 160672"),
            # Non-numeric Account ID — raised by bing_ads_source.get_rows. The matched phrase
            # precedes the volatile account id in the message.
            (
                "Bing Ads Account ID must be numeric",
                "Bing Ads Account ID must be numeric. The configured Account ID 'F118FDGN' is not a number — "
                "you may have entered your alphanumeric Account Number instead. Update the Account ID in the "
                "source settings and try again.",
            ),
            # Deterministic credential/config errors raised in source_for_pipeline.
            ("Bing Ads access token not found", "Bing Ads access token not found for job abc"),
            ("Bing Ads refresh token not found", "Bing Ads refresh token not found for job abc"),
            ("Bing Ads developer token not configured", "Bing Ads developer token not configured"),
            (
                "Bing Ads OAuth application credentials not configured",
                "Bing Ads OAuth application credentials not configured",
            ),
        ],
    )
    def test_get_non_retryable_errors_pattern_recognised(self, pattern, raised_message):
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert pattern in non_retryable_errors
        assert pattern in raised_message

    @pytest.mark.parametrize(
        "transient_message",
        [
            # Plain transport-level failures — must NOT match any non-retryable pattern,
            # otherwise the schema would be disabled after the first few transient failures.
            "Failed to fetch customer ID: ConnectionError: HTTPSConnectionPool(host='bingads.microsoft.com', port=443): Max retries exceeded",
            "Failed to fetch customer ID: TimeoutError: The read operation timed out",
            "Failed to fetch customer ID: WebFault: Server raised fault: 'Internal Error'",
            "Failed to fetch customer ID: HTTPError: 503 Server Error: Service Unavailable",
        ],
    )
    def test_get_non_retryable_errors_does_not_match_transient_failures(self, transient_message):
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert not any(pattern in transient_message for pattern in non_retryable_errors)

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

    def test_transient_bing_internal_error_fault_stays_retryable(self):
        # A generic Bing-side fault ("Internal Error") is transient and must keep retrying — it must not
        # be caught by the "Invalid client data" pattern.
        non_retryable_errors = self.source.get_non_retryable_errors()
        transient_message = "Server raised fault: 'Internal Error. TrackingId: abc-123.'"

        assert not any(pattern in transient_message for pattern in non_retryable_errors)

    def test_get_resumable_source_manager(self):
        """Test that get_resumable_source_manager returns a manager that round-trips BingAdsResumeConfig."""
        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "test-job-id"
        inputs.logger = mock.MagicMock()

        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)

        store: dict[str, bytes] = {}
        fake_redis = mock.MagicMock()
        fake_redis.set.side_effect = lambda key, value, ex=None: store.__setitem__(key, value)
        fake_redis.get.side_effect = lambda key: store.get(key)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable.get_client",
            return_value=fake_redis,
        ):
            original = BingAdsResumeConfig(next_start_date="2025-02-01", end_date="2025-06-30")
            manager.save_state(original)
            loaded = manager.load_state()

        assert isinstance(loaded, BingAdsResumeConfig)
        assert loaded == original
