import json
from datetime import date

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import VersionDeprecation
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.linkedinads import (
    LinkedinAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.client import LinkedinAdsClient
from products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.source import (
    LINKEDIN_ADS_VERSION_202606,
    LINKEDIN_ADS_VERSION_202607,
    LINKEDIN_ADS_VERSION_202608,
    LinkedInAdsSource,
)


class TestLinkedInAdsSource:
    """Test suite for LinkedInAdsSource class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.source = LinkedInAdsSource()
        self.team_id = 123
        self.config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=456, account_id="789")

    def test_defaults_new_sources_to_202608(self):
        assert self.source.default_version == LINKEDIN_ADS_VERSION_202608
        assert set(self.source.supported_versions) == {
            "v1",
            LINKEDIN_ADS_VERSION_202606,
            LINKEDIN_ADS_VERSION_202607,
            LINKEDIN_ADS_VERSION_202608,
        }

    def test_deprecated_versions_carry_sunset_dates(self):
        # "v1" backs the sunset 202508 header (see client.API_VERSION); 202606 sunsets 2027-06-15.
        # The in-product deprecation banner depends on this metadata staying declared, and the default
        # (202608) must never appear here.
        assert self.source.deprecated_versions == (
            VersionDeprecation(version="v1", sunset_at=date(2026, 8, 1)),
            VersionDeprecation(version=LINKEDIN_ADS_VERSION_202606, sunset_at=date(2027, 6, 15)),
        )
        assert self.source.default_version not in {d.version for d in self.source.deprecated_versions}

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.linkedin_ads.source.linkedin_ads_client_for_integration"
    )
    def test_get_oauth_accounts_uses_default_version_header(self, mock_client_for_integration):
        # The account picker must track the default version's header, not the client's legacy default,
        # so listing doesn't break for new sources once the oldest declared header sunsets.
        mock_client_for_integration.return_value.get_accounts.return_value = []

        self.source.get_oauth_accounts(integration_id=456, team_id=self.team_id)

        assert mock_client_for_integration.call_args.kwargs["api_version"] == "202608"

    def test_demographic_breakdowns_are_offered_but_not_enabled_by_default(self):
        # These fan out to one row per day per demographic value on top of the performance tables,
        # so auto-enabling them would multiply every existing connection's sync cost.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        demographic_tables = [name for name in schemas if name.startswith("member_")]
        assert sorted(demographic_tables) == [
            "member_company_size_stats",
            "member_company_stats",
            "member_country_stats",
            "member_industry_stats",
            "member_job_title_stats",
            "member_seniority_stats",
        ]
        assert all(not schemas[name].should_sync_default for name in demographic_tables)
        assert all(schemas[name].supports_incremental for name in demographic_tables)

        for name in ("accounts", "campaigns", "campaign_groups", "creatives", "conversions"):
            assert schemas[name].should_sync_default

    def test_validate_credentials_missing_account_id(self):
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
