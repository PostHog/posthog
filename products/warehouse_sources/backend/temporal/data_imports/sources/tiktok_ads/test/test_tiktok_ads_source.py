"""Tests for TikTok Ads source integration."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from unittest.mock import MagicMock, Mock, patch

import structlog
from parameterized import parameterized
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    RequestException,
    Timeout,
)

from posthog.schema import ReleaseStatus

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tiktokads import (
    TikTokAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.source import TikTokAdsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.utils import (
    TIKTOK_NON_RETRYABLE_ERROR_PREFIX,
    TIKTOK_TRANSIENT_ERROR_MESSAGE,
    TikTokAdsAPIError,
    TikTokAdsPaginator,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


class TestTikTokAdsSource:
    """Test suite for TikTok Ads source integration."""

    def setup_method(self):
        """Set up test fixtures."""
        self.source = TikTokAdsSource()
        self.team_id = 123
        self.advertiser_id = "123456789"
        self.integration_id = 456
        self.job_id = str(uuid4())

        self.config = TikTokAdsSourceConfig(advertiser_id=self.advertiser_id, tiktok_integration_id=self.integration_id)

        self.mock_integration = Mock(spec=Integration)
        self.mock_integration.access_token = "test_access_token"
        self.mock_integration.team_id = self.team_id

    @parameterized.expand(
        [
            ("advertiser_deleted", 40001, "The advertiser 123 doesn't exist or has been deleted."),
            ("invalid_parameter", 40002, "Invalid parameter"),
        ]
    )
    def test_non_retryable_paginator_error_matches_source_pattern(self, name, api_code, message):
        """The ValueError the paginator raises for non-retryable codes must match a
        pattern in get_non_retryable_errors, otherwise the job retries forever."""
        paginator = TikTokAdsPaginator()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": api_code, "message": message, "data": {}}

        with pytest.raises(ValueError) as exc_info:
            paginator.update_state(mock_response)

        error_message = str(exc_info.value)
        patterns = self.source.get_non_retryable_errors()
        assert any(pattern in error_message for pattern in patterns), (
            f"TikTok non-retryable error '{error_message}' does not match any non-retryable pattern"
        )

    @parameterized.expand(
        [
            ("video", "advertiser does not grant you /file/video/ad/search/:GET permission"),
            ("image", "advertiser does not grant you /file/image/ad/search/:GET permission"),
        ]
    )
    def test_creative_permission_denied_is_non_retryable(self, name, message):
        """Reconnecting is the only fix for a denial, so retrying it would loop forever."""
        paginator = TikTokAdsPaginator()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 40001, "message": message, "data": {}}

        with pytest.raises(ValueError) as exc_info:
            paginator.update_state(mock_response)

        error_message = str(exc_info.value)
        patterns = self.source.get_non_retryable_errors()
        assert any(pattern in error_message for pattern in patterns)

    @parameterized.expand(
        [
            ("video", "advertiser does not grant you /file/video/ad/search/:GET permission"),
            ("image", "advertiser does not grant you /file/image/ad/search/:GET permission"),
        ]
    )
    def test_creative_permission_denied_surfaces_friendly_message(self, name, message):
        """Fails if the dict entries are reordered, which would shadow this message with None."""
        error_message = f"{TIKTOK_NON_RETRYABLE_ERROR_PREFIX} {message} (code: 40001)"

        friendly = [
            friendly_error
            for pattern, friendly_error in self.source.get_non_retryable_errors().items()
            if error_message_matches(error_message, [pattern])
        ]

        assert friendly, "permission denial matched no non-retryable pattern"
        assert friendly[0] is not None, "generic prefix shadowed the creative-permission message"
        assert "creative_videos" in friendly[0]
        assert "creative_images" in friendly[0]

    @parameterized.expand(
        [
            ("report", "advertiser does not grant you /report/integrated/get/:GET permission"),
            ("campaign", "advertiser does not grant you /campaign/get/:GET permission"),
        ]
    )
    def test_non_creative_permission_denied_keeps_raw_message(self, name, message):
        """A denial elsewhere shares the wording, so creative-library advice would contradict it."""
        error_message = f"{TIKTOK_NON_RETRYABLE_ERROR_PREFIX} {message} (code: 40001)"

        friendly = [
            friendly_error
            for pattern, friendly_error in self.source.get_non_retryable_errors().items()
            if error_message_matches(error_message, [pattern])
        ]

        assert friendly, "permission denial matched no non-retryable pattern"
        assert friendly[0] is None

    def test_advertiser_deleted_40001_still_has_no_friendly_message(self):
        """The raw message names the advertiser, so the creative key must not over-match it."""
        error_message = (
            f"{TIKTOK_NON_RETRYABLE_ERROR_PREFIX} The advertiser 123 doesn't exist or has been deleted. (code: 40001)"
        )

        friendly = [
            friendly_error
            for pattern, friendly_error in self.source.get_non_retryable_errors().items()
            if error_message_matches(error_message, [pattern])
        ]

        assert friendly, "deleted advertiser matched no non-retryable pattern"
        assert friendly[0] is None

    def test_creative_permission_denied_does_not_match_get_retryable_errors(self):
        """A permission denial must not be swallowed as a benign retryable error."""
        paginator = TikTokAdsPaginator()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 40001,
            "message": "advertiser does not grant you /file/video/ad/search/:GET permission",
            "data": {},
        }

        with pytest.raises(ValueError) as exc_info:
            paginator.update_state(mock_response)

        error_message = str(exc_info.value)
        patterns = self.source.get_retryable_errors()
        assert not any(pattern in error_message for pattern in patterns)

    @parameterized.expand(
        [
            ("deleted_integration", "ValueError: Integration not found: 173586"),
            ("missing_integration", "Integration not found: 456"),
        ]
    )
    def test_deleted_integration_is_non_retryable(self, name, observed_error):
        """A deleted/disconnected integration (get_oauth_integration raising
        "Integration not found: <id>") must be recognised as non-retryable —
        retrying can't recreate the row, the customer has to reconnect."""
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(pattern in observed_error for pattern in non_retryable_errors)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error for url: https://business-api.tiktok.com/open_api/v1.3/campaign/get/"),
            ("connection_reset", "ConnectionError: Connection reset by peer"),
        ]
    )
    def test_transient_errors_stay_retryable(self, name, observed_error):
        """Transient infrastructure failures must NOT be classified as non-retryable."""
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(pattern in observed_error for pattern in non_retryable_errors)

    def test_retryable_paginator_error_does_not_match_source_pattern(self):
        """Retryable rate-limit/server errors must NOT be classified as non-retryable."""
        paginator = TikTokAdsPaginator()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 50000, "message": "Internal server error", "data": {}}

        # Retryable codes raise TikTokAdsAPIError, not ValueError; capture its message.
        with pytest.raises(Exception) as exc_info:
            paginator.update_state(mock_response)

        error_message = str(exc_info.value)
        patterns = self.source.get_non_retryable_errors()
        assert not any(pattern in error_message for pattern in patterns)

    @parameterized.expand(
        [
            ("system_error", 50000, "System error"),
            ("rate_limited", 40100, "Requests made too frequently"),
            ("maintenance", 60001, "The system is in maintenance"),
            # Internal service error TikTok itself asks callers to retry — must not raise the
            # non-retryable ValueError the else-branch raises for unclassified codes.
            ("internal_service_error", 51002, "Internal service error. Please retry later."),
        ]
    )
    def test_retryable_paginator_error_matches_get_retryable_errors(self, name, api_code, message):
        """A mid-pagination TikTok error the paginator already classifies as transient must
        match get_retryable_errors, otherwise Temporal's outer retry reports it as a bug on
        every attempt instead of logging a warning."""
        paginator = TikTokAdsPaginator()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": api_code, "message": message, "data": {}}

        with pytest.raises(TikTokAdsAPIError) as exc_info:
            paginator.update_state(mock_response)

        error_message = str(exc_info.value)
        patterns = self.source.get_retryable_errors()
        assert any(pattern in error_message for pattern in patterns), (
            f"TikTok retryable error '{error_message}' does not match any retryable pattern"
        )

    def test_non_retryable_paginator_error_does_not_match_get_retryable_errors(self):
        """A non-retryable paginator error must not be swallowed as a benign retryable one."""
        paginator = TikTokAdsPaginator()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"code": 40001, "message": "The advertiser doesn't exist", "data": {}}

        with pytest.raises(ValueError) as exc_info:
            paginator.update_state(mock_response)

        error_message = str(exc_info.value)
        patterns = self.source.get_retryable_errors()
        assert not any(pattern in error_message for pattern in patterns)

    @parameterized.expand(
        [
            ("connection_reset", RequestsConnectionError("Connection reset by peer")),
            ("timeout", Timeout("Read timed out")),
            ("base_request_exception", RequestException("DNS lookup failed")),
        ]
    )
    def test_get_oauth_accounts_maps_transport_failure_to_transient(self, name, exception):
        """A network failure (DNS/reset/timeout) raises a bare RequestException, not HTTPError,
        so it must still map to the actionable transient message instead of escaping as a 500."""
        _MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.source"
        with (
            patch.object(self.source, "get_oauth_integration", return_value=self.mock_integration),
            patch(f"{_MODULE}.list_advertisers", side_effect=exception),
        ):
            with pytest.raises(IntegrationAccountListingError) as exc_info:
                self.source.get_oauth_accounts(self.integration_id, self.team_id)

        assert str(exc_info.value) == TIKTOK_TRANSIENT_ERROR_MESSAGE

    @parameterized.expand(
        [
            ("invalid_access_token", 40105, "Invalid access_token"),
            ("no_advertiser_permission", 40110, "No permission to access this advertiser"),
            (
                "app_token_mismatch",
                40000,
                "The app_id is inconsistent with the token's app information. Please retry after correcting it.",
            ),
        ]
    )
    def test_get_oauth_accounts_maps_auth_errors_to_reconnect_message(self, name, api_code, message):
        """Auth-rejection responses — including the app/token mismatch TikTok returns under the
        generic 40000 code — must surface as an actionable reconnect message, not escape as a bug."""
        _MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.source"
        error = TikTokAdsAPIError(message, api_code=api_code)
        with (
            patch.object(self.source, "get_oauth_integration", return_value=self.mock_integration),
            patch(f"{_MODULE}.list_advertisers", side_effect=error),
        ):
            with pytest.raises(IntegrationAccountListingError) as exc_info:
                self.source.get_oauth_accounts(self.integration_id, self.team_id)

        assert "reconnect your TikTok Ads integration" in str(exc_info.value)

    def test_get_oauth_accounts_does_not_treat_other_40000_errors_as_auth(self):
        """Code 40000 is a generic params-error bucket with many unrelated messages — only the
        specific app/token mismatch text should map to the reconnect message; anything else must
        keep surfacing as a bug so real request-construction errors aren't hidden."""
        _MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.source"
        error = TikTokAdsAPIError("Invalid parameter: advertiser_id", api_code=40000)
        with (
            patch.object(self.source, "get_oauth_integration", return_value=self.mock_integration),
            patch(f"{_MODULE}.list_advertisers", side_effect=error),
        ):
            with pytest.raises(TikTokAdsAPIError):
                self.source.get_oauth_accounts(self.integration_id, self.team_id)

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "TikTokAds"
        assert config.label == "TikTok Ads"
        assert config.releaseStatus == ReleaseStatus.GA
        assert len(config.fields) == 2

        # OAuth field comes first — the account selector below reads from it
        integration_field = config.fields[0]
        assert integration_field.name == "tiktok_integration_id"
        assert hasattr(integration_field, "kind") and integration_field.kind == "tiktok-ads"

        advertiser_field = config.fields[1]
        assert advertiser_field.name == "advertiser_id"
        assert hasattr(advertiser_field, "required") and advertiser_field.required is True
        assert getattr(advertiser_field, "integrationField", None) == "tiktok_integration_id"

    @parameterized.expand(
        [
            ("missing_advertiser_id", "", 123, False, "Advertiser ID and TikTok Ads integration are required"),
            (
                "missing_integration_id",
                "123456789",
                0,
                False,
                "Advertiser ID and TikTok Ads integration are required",
            ),
            ("valid_credentials", "test_advertiser", 123, True, None),
        ]
    )
    def test_validate_credentials(self, name, advertiser_id, integration_id, expected_valid, expected_error):
        config = TikTokAdsSourceConfig(advertiser_id=advertiser_id, tiktok_integration_id=integration_id)

        with patch.object(self.source, "get_oauth_integration") as mock_get_integration:
            if expected_valid:
                mock_get_integration.return_value = self.mock_integration
            else:
                mock_get_integration.side_effect = Exception("Integration not found")

            is_valid, error = self.source.validate_credentials(config, self.team_id)

            assert is_valid == expected_valid
            if expected_error:
                assert expected_error in str(error)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        expected_schemas = {
            "campaigns",
            "ad_groups",
            "ads",
            "creative_videos",
            "creative_images",
            "campaign_report",
            "ad_group_report",
            "ad_report",
            "campaign_demographic_report",
            "campaign_country_report",
            "campaign_platform_report",
            "ad_group_demographic_report",
            "ad_group_country_report",
            "ad_group_platform_report",
            "ad_demographic_report",
            "ad_country_report",
            "ad_platform_report",
        }
        actual_schema_names = {schema.name for schema in schemas}

        assert actual_schema_names == expected_schemas

        for schema in schemas:
            if "report" in schema.name:
                assert schema.supports_incremental is True
                field_names = [field["field"] for field in schema.incremental_fields]
                assert "stat_time_day" in field_names
            else:
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []

    def test_only_breakdown_and_creative_tables_are_off_by_default(self):
        # New tables land in the schema picker pre-ticked. The breakdown reports fan every
        # entity-day out across its dimension values, and the creative tables need a grant most
        # advertisers withhold, so both stay opt-in while the rest stay selected.
        should_sync = {schema.name: schema.should_sync_default for schema in self.source.get_schemas(self.config, 1)}

        off_by_default = {name for name, default in should_sync.items() if not default}

        assert off_by_default == {
            "creative_videos",
            "creative_images",
            "campaign_demographic_report",
            "campaign_country_report",
            "campaign_platform_report",
            "ad_group_demographic_report",
            "ad_group_country_report",
            "ad_group_platform_report",
            "ad_demographic_report",
            "ad_country_report",
            "ad_platform_report",
        }

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.source.tiktok_ads_source")
    def test_source_for_pipeline_success(self, mock_tiktok_source):
        inputs = SourceInputs(
            schema_name="campaigns",
            schema_id="campaigns_schema",
            source_id="source-id",
            team_id=self.team_id,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime.now() - timedelta(days=1),
            db_incremental_field_earliest_value=None,
            incremental_field="modify_time",
            incremental_field_type=IncrementalFieldType.DateTime,
            job_id=self.job_id,
            logger=structlog.get_logger(),
            reset_pipeline=False,
        )

        mock_response = Mock()
        mock_tiktok_source.return_value = mock_response
        manager = MagicMock()

        with patch.object(self.source, "get_oauth_integration") as mock_get_integration:
            mock_get_integration.return_value = self.mock_integration

            result = self.source.source_for_pipeline(self.config, manager, inputs)

            assert result == mock_response
            mock_tiktok_source.assert_called_once_with(
                advertiser_id=self.advertiser_id,
                endpoint="campaigns",
                team_id=self.team_id,
                job_id=self.job_id,
                access_token="test_access_token",
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=inputs.db_incremental_field_last_value,
            )

    def test_source_for_pipeline_no_access_token(self):
        inputs = SourceInputs(
            schema_name="campaigns",
            schema_id="campaigns_schema",
            source_id="source-id",
            team_id=self.team_id,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
            incremental_field=None,
            incremental_field_type=None,
            job_id=self.job_id,
            logger=structlog.get_logger(),
            reset_pipeline=False,
        )

        self.mock_integration.access_token = None

        with patch.object(self.source, "get_oauth_integration") as mock_get_integration:
            mock_get_integration.return_value = self.mock_integration

            with pytest.raises(ValueError, match="TikTok Ads access token not found"):
                self.source.source_for_pipeline(self.config, MagicMock(), inputs)

    def test_validate_credentials_exception_handling(self):
        config = TikTokAdsSourceConfig(advertiser_id="123456789", tiktok_integration_id=123)

        with patch.object(self.source, "get_oauth_integration") as mock_get_integration:
            mock_get_integration.side_effect = Exception("Network error")

            is_valid, error = self.source.validate_credentials(config, self.team_id)

            assert is_valid is False
            assert "Failed to validate TikTok Ads credentials" in str(error)
