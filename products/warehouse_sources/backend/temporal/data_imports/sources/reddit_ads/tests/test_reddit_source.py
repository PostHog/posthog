from typing import Any

import pytest
from unittest import mock

from requests.exceptions import Timeout

from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.redditads import (
    RedditAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.reddit_ads import (
    RedditAdsApiError,
    RedditAdsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.source import RedditAdsSource


class TestRedditAdsSource:
    """Test suite for RedditAdsSource class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.source = RedditAdsSource()
        self.team_id = 123
        self.config = RedditAdsSourceConfig(reddit_integration_id=456, account_id="789")

    def test_validate_credentials_missing_account_id(self):
        invalid_config = RedditAdsSourceConfig(reddit_integration_id=456, account_id="")

        is_valid, error_message = self.source.validate_credentials(invalid_config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert "Account ID and Reddit Ads integration are required" in error_message

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.source.RedditAdsSource.get_oauth_integration"
    )
    def test_validate_credentials_success(self, mock_get_oauth_integration):
        mock_integration = mock.MagicMock()
        mock_integration.access_token = "test_token"
        mock_get_oauth_integration.return_value = mock_integration

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_get_oauth_integration.assert_called_once_with(self.config.reddit_integration_id, self.team_id)

    @pytest.mark.parametrize(
        "side_effect,expected_error_fragment,expect_capture_called",
        [
            # A deleted/disconnected integration is an expected user state — surface a clean
            # "reconnect" message and do NOT report it to error tracking.
            (ValueError("Integration not found: 154683"), "Reddit Ads integration not found", False),
            # Anything else is genuinely unexpected and must still be captured.
            (Exception("OAuth error"), "Failed to validate Reddit Ads credentials", True),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.source.RedditAdsSource.get_oauth_integration"
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.source.capture_exception")
    def test_validate_credentials_oauth_failures(
        self,
        mock_capture_exception,
        mock_get_oauth_integration,
        side_effect,
        expected_error_fragment,
        expect_capture_called,
    ):
        """Validation distinguishes an expected missing integration from a genuine error."""
        mock_get_oauth_integration.side_effect = side_effect

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert expected_error_fragment in error_message
        assert mock_capture_exception.called is expect_capture_called

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.source.OauthIntegration")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.source.RedditAdsSource.get_oauth_integration"
    )
    def test_get_oauth_accounts_refresh_network_failure_is_actionable(
        self, mock_get_oauth_integration, mock_oauth_integration_cls
    ):
        """A refresh that fails before an HTTP response (timeout) must surface actionable guidance,
        not an unhandled 500 — it raises before ERROR_TOKEN_REFRESH_FAILED is recorded."""
        integration = mock.MagicMock()
        integration.errors = ""
        integration.access_token = "expired_token"
        mock_get_oauth_integration.return_value = integration

        oauth = mock_oauth_integration_cls.return_value
        oauth.access_token_expired.return_value = True
        oauth.refresh_access_token.side_effect = Timeout("connection timed out")

        with pytest.raises(IntegrationAccountListingError) as excinfo:
            self.source.get_oauth_accounts(self.config.reddit_integration_id, self.team_id)

        assert "try again" in str(excinfo.value).lower()

    @pytest.mark.parametrize(
        "status_code,expected_fragment",
        [
            (401, "reconnect"),
            (403, "reconnect"),
            # /me/businesses and /businesses/{id}/ad_accounts are static, real paths, so a 404 there
            # means no accessible business/ad account for these credentials, not a bad request.
            (404, "couldn't find any businesses or ad accounts"),
            (429, "try again"),
            (500, "try again"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.source.OauthIntegration")
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.source.RedditAdsSource.get_oauth_integration"
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.reddit_ads.source.list_businesses")
    def test_get_oauth_accounts_maps_reddit_api_errors_to_actionable_messages(
        self,
        mock_list_businesses,
        mock_get_oauth_integration,
        mock_oauth_integration_cls,
        status_code,
        expected_fragment,
    ):
        """Every status Reddit can return from listing businesses/ad accounts must surface a clean,
        actionable message instead of an unhandled 500 — regression for the 404 that escaped raw."""
        integration = mock.MagicMock()
        integration.errors = ""
        integration.access_token = "valid_token"
        mock_get_oauth_integration.return_value = integration

        oauth = mock_oauth_integration_cls.return_value
        oauth.access_token_expired.return_value = False

        mock_list_businesses.side_effect = RedditAdsApiError("boom", status_code)

        with pytest.raises(IntegrationAccountListingError) as excinfo:
            self.source.get_oauth_accounts(self.config.reddit_integration_id, self.team_id)

        assert expected_fragment in str(excinfo.value).lower()

    def _drive(self, schema_name: str, script: list[ScriptedResponse], access_token: str | None, **inputs: Any):
        integration = mock.MagicMock(access_token=access_token)
        with mock.patch.object(RedditAdsSource, "get_oauth_integration", return_value=integration) as get_integration:
            result = SourceDriver(self.source, self.config).run(schema_name, script, **inputs)
        return result, get_integration

    def test_source_for_pipeline_success(self):
        result, get_integration = self._drive(
            "campaigns", [ScriptedResponse(json={"data": [], "pagination": {}})], "test_token", team_id=self.team_id
        )

        assert result.raised is None
        get_integration.assert_called_once_with(self.config.reddit_integration_id, self.team_id)
        assert result.paths == ["/api/v3/ad_accounts/789/campaigns"]
        assert result.requests[0].headers["authorization"] == "Bearer test_token"
        assert result.requests[0].param("modified_at[after]") is None
        assert result.response is not None
        assert result.response.name == "campaigns"

    def test_source_for_pipeline_no_access_token(self):
        result, _ = self._drive("campaigns", [], None, job_id="test_job")

        assert isinstance(result.raised, ValueError)
        assert "Reddit Ads access token not found for job test_job" in str(result.raised)
        assert result.requests == []

    def test_source_for_pipeline_with_incremental(self):
        result, _ = self._drive(
            "campaign_report",
            [ScriptedResponse(json={"data": {"metrics": []}, "pagination": {}})],
            "test_token",
            incremental_field="date",
            db_incremental_field_last_value="2024-03-15",
        )

        assert result.requests[0].method == "POST"
        assert result.requests[0].json()["data"]["starts_at"] == "2024-03-15T00:00:00Z"
        assert result.response is not None
        assert result.response.name == "campaign_report"


class TestRedditAdsResumeBehavior:
    """End-to-end resume behavior of the Reddit Ads source."""

    def _run_campaigns(self, responses: list[ScriptedResponse], **kwargs: Any):
        driver = SourceDriver(RedditAdsSource(), RedditAdsSourceConfig(reddit_integration_id=456, account_id="789"))
        integration = mock.MagicMock(access_token="test_token")
        with mock.patch.object(RedditAdsSource, "get_oauth_integration", return_value=integration):
            return driver.run("campaigns", responses, **kwargs)

    def test_fresh_run_saves_state_after_each_non_terminal_page(self):
        """No saved state: first page yields, the next_url is saved."""
        result = self._run_campaigns(
            [
                ScriptedResponse(
                    json={
                        "data": [{"id": "c1", "modified_at": "2024-01-01T00:00:00Z"}],
                        "pagination": {
                            "next_url": "https://ads-api.reddit.com/api/v3/ad_accounts/789/campaigns?page=2"
                        },
                    }
                ),
                ScriptedResponse(
                    json={"data": [{"id": "c2", "modified_at": "2024-01-02T00:00:00Z"}], "pagination": {}}
                ),
            ]
        )

        # Resume state is persisted only once — after the first (non-terminal) page.
        assert result.saved_states == [
            RedditAdsResumeConfig(next_url="https://ads-api.reddit.com/api/v3/ad_accounts/789/campaigns?page=2")
        ]

    def test_resume_uses_saved_cursor(self):
        """A saved next_url: the first request goes there, not to the initial path."""
        result = self._run_campaigns(
            [ScriptedResponse(json={"data": [{"id": "c7", "modified_at": "2024-01-07T00:00:00Z"}], "pagination": {}})],
            resume_state=RedditAdsResumeConfig(
                next_url="https://ads-api.reddit.com/api/v3/ad_accounts/789/campaigns?page=7"
            ),
        )

        assert result.urls == ["https://ads-api.reddit.com/api/v3/ad_accounts/789/campaigns?page=7"]
