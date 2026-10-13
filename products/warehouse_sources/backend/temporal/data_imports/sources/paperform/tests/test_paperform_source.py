import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paperform import (
    PaperformSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.source import PaperformSource


class TestPaperformSource:
    def setup_method(self) -> None:
        self.source = PaperformSource()
        self.team_id = 123
        self.config = PaperformSourceConfig(api_key="pf-key")

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.paperform.co/v1/forms?limit=100",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.paperform.co/v1/spaces?limit=100",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.paperform.co/v1/forms"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.paperform.co/v1/forms"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.paperform.source.validate_credentials"
    )
    def test_validate_credentials_delegates_with_api_key(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in paperform.validate_credentials; here we only assert
        # the source probes with the configured key and returns the delegate's verdict unchanged.
        mock_validate.return_value = (False, "Invalid Paperform API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("pf-key")
        assert result == (False, "Invalid Paperform API key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.paperform.source.paperform_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "submissions"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "pf-key"
        assert kwargs["endpoint"] == "submissions"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.paperform.source.paperform_source")
    def test_source_for_pipeline_drops_watermark_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "submissions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        # A full refresh must re-read everything, even when a stale watermark is still stored.
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Paperform schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
