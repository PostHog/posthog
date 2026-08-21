import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.replyio import (
    ReplyIoSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.source import ReplyIoSource


class TestReplyIoSource:
    def setup_method(self) -> None:
        self.source = ReplyIoSource()
        self.team_id = 123
        self.config = ReplyIoSourceConfig(api_key="reply-key")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.source.check_endpoint_permissions"
    )
    def test_get_endpoint_permissions_delegates(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = {"contacts": None}
        result = self.source.get_endpoint_permissions(self.config, self.team_id, ["contacts"])
        mock_check.assert_called_once_with("reply-key", ["contacts"])
        assert result == {"contacts": None}

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.reply_io.source.reply_io_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "contacts"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "reply-key"
        assert kwargs["endpoint"] == "contacts"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Reply.io schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
