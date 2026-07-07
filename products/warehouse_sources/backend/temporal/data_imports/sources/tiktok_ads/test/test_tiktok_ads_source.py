"""Tests for TikTok Ads source integration."""

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from unittest.mock import MagicMock, Mock, patch

import structlog
from parameterized import parameterized

from posthog.schema import ReleaseStatus

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TikTokAdsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.source import TikTokAdsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.utils import TikTokAdsPaginator
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType


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

    def test_source_type(self):
        """Test that source type is correctly identified."""
        assert self.source.source_type == ExternalDataSourceType.TIKTOKADS

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

    def test_get_source_config(self):
        """Test source configuration generation."""
        config = self.source.get_source_config

        assert config.name.value == "TikTokAds"
        assert config.label == "TikTok Ads"
        assert config.releaseStatus == ReleaseStatus.GA
        assert len(config.fields) == 2

        advertiser_field = config.fields[0]
        assert advertiser_field.name == "advertiser_id"
        assert hasattr(advertiser_field, "required") and advertiser_field.required is True

        integration_field = config.fields[1]
        assert integration_field.name == "tiktok_integration_id"
        assert hasattr(integration_field, "kind") and integration_field.kind == "tiktok-ads"

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
        """Test credential validation scenarios."""
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
        """Test schema retrieval."""
        schemas = self.source.get_schemas(self.config, self.team_id)

        expected_schemas = {"campaigns", "ad_groups", "ads", "campaign_report", "ad_group_report", "ad_report"}
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

    def test_get_resumable_source_manager(self):
        """The source must expose a ResumableSourceManager instance."""
        inputs = MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = self.job_id
        inputs.logger = MagicMock()

        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.tiktok_ads.source.tiktok_ads_source")
    def test_source_for_pipeline_success(self, mock_tiktok_source):
        """Test successful pipeline source creation."""
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
        """Test pipeline source creation fails without access token."""
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
        """Test credential validation handles exceptions properly."""
        config = TikTokAdsSourceConfig(advertiser_id="123456789", tiktok_integration_id=123)

        with patch.object(self.source, "get_oauth_integration") as mock_get_integration:
            mock_get_integration.side_effect = Exception("Network error")

            is_valid, error = self.source.validate_credentials(config, self.team_id)

            assert is_valid is False
            assert "Failed to validate TikTok Ads credentials" in str(error)
