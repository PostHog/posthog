from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from unittest import mock

import requests

from products.warehouse_sources.sources.pinterest_ads._config import PinterestAdsSourceConfig
from products.warehouse_sources.sources.pinterest_ads.source import PinterestAdsSource
from products.warehouse_sources.sources.sdk import IntegrationAccount, IntegrationAccountListingError


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

    @mock.patch("products.warehouse_sources.sources.pinterest_ads.source.PinterestAdsSource.get_oauth_integration")
    def test_validate_credentials_success(self, mock_get_oauth):
        mock_get_oauth.return_value = mock.MagicMock()

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None

    @pytest.mark.parametrize(
        "side_effect,expected_error_fragment,expect_capture_called",
        [
            # A deleted/disconnected integration is an expected user state — surface a clean
            # "reconnect" message and do NOT report it to error tracking.
            (ValueError("Integration not found: 162559"), "Pinterest Ads integration not found", False),
            # Anything else is genuinely unexpected and must still be captured.
            (Exception("OAuth error"), "Failed to validate Pinterest Ads credentials", True),
        ],
    )
    @mock.patch("products.warehouse_sources.sources.pinterest_ads.source.PinterestAdsSource.get_oauth_integration")
    @mock.patch("products.warehouse_sources.sources.pinterest_ads.source.capture_exception")
    def test_validate_credentials_integration_error(
        self, mock_capture, mock_get_oauth, side_effect, expected_error_fragment, expect_capture_called
    ):
        mock_get_oauth.side_effect = side_effect

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message is not None
        assert expected_error_fragment in error_message
        assert mock_capture.called is expect_capture_called

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

    @mock.patch("products.warehouse_sources.sources.pinterest_ads.source.PinterestAdsSource.get_oauth_integration")
    def test_source_for_pipeline_success(self, mock_get_oauth):
        mock_integration = mock.MagicMock()
        mock_integration.access_token = "test_token"
        mock_get_oauth.return_value = mock_integration

        with mock.patch(
            "products.warehouse_sources.sources.pinterest_ads.source.pinterest_ads_source"
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

    @mock.patch("products.warehouse_sources.sources.pinterest_ads.source.PinterestAdsSource.get_oauth_integration")
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
    @mock.patch("products.warehouse_sources.sources.pinterest_ads.source.list_ad_accounts")
    @mock.patch("products.warehouse_sources.sources.pinterest_ads.source.build_session")
    @mock.patch("products.warehouse_sources.sources.pinterest_ads.source.OauthIntegration")
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


_PINTEREST_SOURCE_MODULE = "products.warehouse_sources.sources.pinterest_ads.source"


def _pinterest_http_error(status_code: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(f"{status_code} Client Error", response=response)


class TestPinterestAdsGetOAuthAccounts:
    @contextmanager
    def _listing(self, *, token_expired: bool = False) -> Iterator[tuple[mock.MagicMock, mock.MagicMock]]:
        integration = mock.MagicMock(errors="", access_token="token")
        with (
            mock.patch.object(PinterestAdsSource, "get_oauth_integration", return_value=integration),
            mock.patch(f"{_PINTEREST_SOURCE_MODULE}.OauthIntegration") as mock_oauth,
            mock.patch(f"{_PINTEREST_SOURCE_MODULE}.build_session"),
            mock.patch(f"{_PINTEREST_SOURCE_MODULE}.list_ad_accounts") as mock_list,
        ):
            mock_oauth.return_value.access_token_expired.return_value = token_expired
            yield mock_oauth, mock_list

    def test_maps_accounts_with_permission_badges(self) -> None:
        with self._listing() as (_, mock_list):
            mock_list.return_value = [
                {"id": "549770029420", "name": "Example Inc", "permissions": ["OWNER"]},
                {"id": "111", "name": "Client", "permissions": ["CAMPAIGN_MANAGER"]},
            ]
            accounts = PinterestAdsSource().get_oauth_accounts(456, 123)

        assert accounts == [
            IntegrationAccount(value="549770029420", display_name="Example Inc", badges=("Owner",)),
            IntegrationAccount(value="111", display_name="Client", badges=("Campaign manager",)),
        ]

    @pytest.mark.parametrize(
        "status_code, expected_fragment",
        [
            (401, "reconnect"),
            (403, "reconnect"),
            # Pinterest rate-limits `/ad_accounts` and returns 5xx during outages. Neither is a bug
            # on our side, so the picker asks the user to try again.
            (429, "try again"),
            (500, "try again"),
            (503, "try again"),
        ],
    )
    def test_http_errors_map_to_actionable_listing_errors(self, status_code: int, expected_fragment: str) -> None:
        with self._listing() as (_, mock_list):
            mock_list.side_effect = _pinterest_http_error(status_code)
            with pytest.raises(IntegrationAccountListingError) as exc_info:
                PinterestAdsSource().get_oauth_accounts(456, 123)

        assert expected_fragment in str(exc_info.value).lower()

    def test_a_request_pinterest_does_not_recognise_propagates(self) -> None:
        # A 404 means we built a bad request, which the user cannot fix.
        with self._listing() as (_, mock_list):
            mock_list.side_effect = _pinterest_http_error(404)
            with pytest.raises(requests.HTTPError):
                PinterestAdsSource().get_oauth_accounts(456, 123)

    def test_unreachable_token_endpoint_asks_the_user_to_retry(self) -> None:
        # `refresh_access_token` records a refusal in `integration.errors`, but a network failure
        # escapes as an exception.
        with self._listing(token_expired=True) as (mock_oauth, mock_list):
            mock_oauth.return_value.refresh_access_token.side_effect = requests.ConnectionError("boom")
            with pytest.raises(IntegrationAccountListingError, match="try again"):
                PinterestAdsSource().get_oauth_accounts(456, 123)

        mock_list.assert_not_called()
