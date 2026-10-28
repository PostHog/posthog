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

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.flexmail.source.validate_credentials")
    def test_validate_credentials_delegates_with_credentials(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in flexmail.validate_credentials; here we only assert
        # the source probes with the configured credentials and returns the delegate's verdict.
        mock_validate.return_value = (False, "Invalid Flexmail account ID or personal access token")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("12345", "flexmail-token")
        assert result == (False, "Invalid Flexmail account ID or personal access token")

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
