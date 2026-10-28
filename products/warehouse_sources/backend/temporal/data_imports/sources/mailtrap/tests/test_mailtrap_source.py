from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
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

    def test_source_for_pipeline_drops_watermark_on_full_refresh(self) -> None:
        # A stale watermark left over from a previous incremental sync must not leak into a full
        # refresh, or the refresh silently skips older history.
        result = SourceDriver(self.source, self.config).run(
            "email_logs",
            [ScriptedResponse(json={"messages": [], "next_page_cursor": None})],
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
        assert result.raised is None
        assert result.params("filters[sent_after]") == [None]
