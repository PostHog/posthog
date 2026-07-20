import json

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client import LinkedinAdsClient
from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.source import (
    LINKEDIN_ADS_VERSION_202606,
    LinkedInAdsSource,
)


class TestLinkedInAdsSource:
    """Test suite for LinkedInAdsSource class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.source = LinkedInAdsSource()
        self.team_id = 123
        self.config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=456, account_id="789")

    @pytest.mark.parametrize(
        "observed_error",
        [
            'LinkedIn API error (404): {"status":404,"code":"RESOURCE_NOT_FOUND","message":"No virtual resource found"}',
            "REVOKED_ACCESS_TOKEN",
            "The token used in the request has expired",
            "Failed to refresh token for LinkedIn Ads integration. Please re-authorize the integration.",
            'LinkedIn API error (401): {"status":401,"serviceErrorCode":65608,"code":"RESTRICTED_MEMBER","message":"Member is restricted"}',
            # Integration.DoesNotExist when the OAuth integration row was deleted/disconnected.
            "Integration matching query does not exist.",
        ],
    )
    def test_non_retryable_errors_match_upstream_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            'LinkedIn API error (retryable, 500): {"message":"Internal Server Error"}',
            'LinkedIn API error (retryable, 429): {"message":"Too many requests"}',
            "Connection reset by peer",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_defaults_new_sources_to_202606(self):
        assert self.source.default_version == LINKEDIN_ADS_VERSION_202606
        assert set(self.source.supported_versions) == {"v1", LINKEDIN_ADS_VERSION_202606}

    @pytest.mark.parametrize(
        "pinned_version,expected_header",
        [
            # Existing sources pinned to the legacy label must keep sending the header they always
            # sent (202508), so their syncs stay byte-for-byte unchanged after the default flip.
            ("v1", "202508"),
            (LINKEDIN_ADS_VERSION_202606, "202606"),
            # No pin resolves to the new default.
            (None, "202606"),
            # An undeclared pin is honored verbatim and passed straight through for LinkedIn to validate.
            ("209901", "209901"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.source.linkedin_ads_source"
    )
    def test_source_for_pipeline_dispatches_resolved_api_version(
        self, mock_linkedin_ads_source, pinned_version, expected_header
    ):
        inputs = mock.MagicMock()
        inputs.api_version = pinned_version
        inputs.should_use_incremental_field = False

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_linkedin_ads_source.call_args.kwargs["api_version"] == expected_header

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.source.linkedin_ads_client_for_integration"
    )
    def test_get_oauth_accounts_uses_default_version_header(self, mock_client_for_integration):
        # The account picker must track the default version's header, not the client's legacy default,
        # so listing doesn't break for new sources once the oldest declared header sunsets.
        mock_client_for_integration.return_value.get_accounts.return_value = []

        self.source.get_oauth_accounts(integration_id=456, team_id=self.team_id)

        assert mock_client_for_integration.call_args.kwargs["api_version"] == "202606"

    def test_validate_credentials_missing_account_id(self):
        """Test credential validation with missing account ID."""
        invalid_config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=456, account_id="")

        is_valid, error_message = self.source.validate_credentials(invalid_config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "Account ID and LinkedIn Ads integration are required" in error_message

    @pytest.mark.parametrize(
        "invalid_account_id",
        [
            "Reed Lnkedin",
            "https://www.linkedin.com/company/recruiteasy-ca",
            " 789",
            "789 ",
            "acc-789",
        ],
    )
    def test_validate_credentials_non_numeric_account_id(self, invalid_account_id):
        invalid_config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=456, account_id=invalid_account_id)

        is_valid, error_message = self.source.validate_credentials(invalid_config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "numeric account ID" in error_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.source.Integration")
    def test_validate_credentials_integration_not_found(self, mock_integration_model):
        """Test credential validation when integration doesn't exist."""

        # Mock DoesNotExist exception
        class MockDoesNotExist(Exception):
            pass

        mock_integration_model.DoesNotExist = MockDoesNotExist
        mock_integration_model.objects.get.side_effect = MockDoesNotExist()

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "LinkedIn Ads integration not found" in error_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.source.Integration")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.source.capture_exception"
    )
    def test_validate_credentials_unexpected_error(self, mock_capture_exception, mock_integration_model):
        """Test credential validation with unexpected error."""

        # Mock DoesNotExist exception
        class MockDoesNotExist(Exception):
            pass

        mock_integration_model.DoesNotExist = MockDoesNotExist
        mock_integration_model.objects.get.side_effect = Exception("Database error")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "Failed to validate LinkedIn Ads credentials" in error_message
        assert "Database error" in error_message
        mock_capture_exception.assert_called_once()

    @pytest.mark.parametrize(
        "observed_error",
        [
            # A non-numeric Account ID raises this 400 — the quoted key value is volatile, the
            # type-coercion phrase is the stable part we match on.
            'LinkedIn API error (400): {"message":"Key value \'Reed%20Lnkedin\' must be of type \'java.lang.Long\'","status":400}',
            'LinkedIn API error (400): {"message":"Key value \'LI\' must be of type \'java.lang.Long\'","status":400}',
        ],
    )
    def test_non_retryable_errors_match_invalid_account_id(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            # Transient transport / 5xx errors must stay retryable.
            "LinkedIn API error (retryable, 503): service unavailable",
            'LinkedIn daily rate limit reached (429): {"message":"throttled","status":429}',
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "invalid_account_id",
        [
            "Reed Lnkedin",
            "https://www.linkedin.com/company/recruiteasy-ca",
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_invalid_account_id_error_is_non_retryable(self, mock_restli_client, invalid_account_id):
        """A malformed Account ID makes LinkedIn reject the accounts URN with a deterministic 400.
        The raised message must match a get_non_retryable_errors pattern, else the job retries forever."""
        body = json.dumps(
            {
                "message": (
                    f"Array parameter 'accounts' value 'urn:li:sponsoredAccount:{invalid_account_id}' is invalid. "
                    f"Reason: Deserializing output 'urn:li:sponsoredAccount:{invalid_account_id}' failed"
                ),
                "status": 400,
            }
        )
        mock_response = mock.MagicMock()
        mock_response.status_code = 400
        mock_response.response.text = body
        mock_restli_client.return_value.finder.return_value = mock_response

        client = LinkedinAdsClient("test_access_token")
        with pytest.raises(Exception) as exc_info:
            client.get_accounts()

        error_message = str(exc_info.value)
        patterns = self.source.get_non_retryable_errors()
        assert any(pattern in error_message for pattern in patterns), (
            f"LinkedIn invalid-account error '{error_message}' does not match any non-retryable pattern"
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client.RestliClient")
    def test_unrelated_400_is_not_classified_as_non_retryable(self, mock_restli_client):
        """The accounts-URN pattern must be specific — an unrelated 400 must not match it."""
        body = json.dumps({"message": "Invalid 'fields' parameter", "status": 400})
        mock_response = mock.MagicMock()
        mock_response.status_code = 400
        mock_response.response.text = body
        mock_restli_client.return_value.finder.return_value = mock_response

        client = LinkedinAdsClient("test_access_token")
        with pytest.raises(Exception) as exc_info:
            client.get_accounts()

        error_message = str(exc_info.value)
        patterns = self.source.get_non_retryable_errors()
        assert not any(pattern in error_message for pattern in patterns)
