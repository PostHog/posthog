import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.partnerize import (
    PartnerizeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.source import PartnerizeSource

INCREMENTAL_ENDPOINTS = {"conversions", "clicks"}


class TestPartnerizeSource:
    def setup_method(self) -> None:
        self.source = PartnerizeSource()
        self.team_id = 123
        self.config = PartnerizeSourceConfig(
            application_key="app-key", user_api_key="api-key", publisher_id="111111l92"
        )

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.partnerize.com/reporting/report_publisher/publisher/111111l92/conversion.json?start_date=2010-01-01T00%3A00%3A00Z&offset=0",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.partnerize.com/reference/country",
            ),
            (
                "unknown_publisher",
                "404 Client Error: Not Found for url: https://api.partnerize.com/user/publisher/111111l92/campaign/a",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            (
                "server_error",
                "500 Server Error: Internal Server Error for url: https://api.partnerize.com/reference/country",
            ),
            (
                "rate_limited",
                "429 Client Error: Too Many Requests for url: https://api.partnerize.com/reference/currency",
            ),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.source.validate_credentials"
    )
    def test_validate_credentials_delegates_with_config_values(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in partnerize.validate_credentials; here we only assert
        # the source probes with the configured credentials and returns the delegate's verdict.
        mock_validate.return_value = (False, "Invalid Partnerize API credentials")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("app-key", "api-key", "111111l92")
        assert result == (False, "Invalid Partnerize API credentials")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.source.partnerize_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "conversions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-05-01 12:00:00"
        inputs.incremental_field = "conversion_time"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["application_key"] == "app-key"
        assert kwargs["user_api_key"] == "api-key"
        assert kwargs["publisher_id"] == "111111l92"
        assert kwargs["endpoint"] == "conversions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01 12:00:00"
        assert kwargs["incremental_field"] == "conversion_time"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.source.partnerize_source")
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "conversions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-05-01 12:00:00"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Partnerize schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
