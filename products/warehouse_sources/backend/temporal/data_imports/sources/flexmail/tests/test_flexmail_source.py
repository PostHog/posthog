import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.source import FlexmailSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.flexmail import (
    FlexmailSourceConfig,
)


class TestFlexmailSource:
    def setup_method(self) -> None:
        self.source = FlexmailSource()
        self.team_id = 123
        self.config = FlexmailSourceConfig(account_id="12345", personal_access_token="flexmail-token")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.source.flexmail_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "contacts"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["account_id"] == "12345"
        assert kwargs["personal_access_token"] == "flexmail-token"
        assert kwargs["endpoint"] == "contacts"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Flexmail schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
