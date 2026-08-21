import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mailtrap import (
    MailtrapSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.source import MailtrapSource

INCREMENTAL_ENDPOINTS = {"email_logs", "suppressions"}


class TestMailtrapSource:
    def setup_method(self) -> None:
        self.source = MailtrapSource()
        self.team_id = 123
        self.config = MailtrapSourceConfig(api_token="token")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.source.mailtrap_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "email_logs"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "email_logs"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mailtrap.source.mailtrap_source")
    def test_source_for_pipeline_drops_watermark_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        # A stale watermark left over from a previous incremental sync must not leak into a full
        # refresh, or the refresh silently skips older history.
        inputs = mock.MagicMock()
        inputs.schema_name = "email_logs"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Mailtrap schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
