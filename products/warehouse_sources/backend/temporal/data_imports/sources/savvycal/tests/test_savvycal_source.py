import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.savvycal import (
    SavvyCalSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.source import SavvyCalSource


class TestSavvyCalSource:
    def setup_method(self) -> None:
        self.source = SavvyCalSource()
        self.team_id = 123
        self.config = SavvyCalSourceConfig(api_key="pt_secret_key")

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.savvycal.com/v1/events",),
            ("403 Client Error: Forbidden for url: https://api.savvycal.com/v1/me",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.savvycal.com/v1/events",),
            ("429 Client Error: Too Many Requests for url: https://api.savvycal.com/v1/links",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.source.validate_credentials")
    def test_validate_credentials_delegates_to_shared_helper(self, mock_validate: mock.MagicMock) -> None:
        # The source method forwards the token to the shared validator and returns its result verbatim.
        mock_validate.return_value = (False, "Invalid SavvyCal personal access token")
        result = self.source.validate_credentials(self.config, self.team_id)
        assert result == (False, "Invalid SavvyCal personal access token")
        mock_validate.assert_called_once_with("pt_secret_key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.source.savvycal_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "pt_secret_key"
        assert kwargs["endpoint"] == "events"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.savvycal.source.savvycal_source")
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_source: mock.MagicMock) -> None:
        # A stale watermark from a previous incremental config must not leak into a full refresh.
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown SavvyCal schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
