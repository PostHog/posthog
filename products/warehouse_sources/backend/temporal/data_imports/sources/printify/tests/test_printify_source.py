from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.printify import (
    PrintifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.printify.source import PrintifySource


class TestPrintifySource:
    def setup_method(self) -> None:
        self.source = PrintifySource()
        self.team_id = 123
        self.config = PrintifySourceConfig(api_key="printify-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.printify.source.validate_credentials")
    def test_validate_credentials_delegates_with_api_key(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in printify.validate_credentials; here we only assert
        # the source probes with the configured token and returns the delegate's verdict unchanged.
        mock_validate.return_value = (False, "Invalid Printify API token")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("printify-key")
        assert result == (False, "Invalid Printify API token")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.printify.source.printify_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "printify-key"
        assert kwargs["endpoint"] == "orders"
        assert kwargs["resumable_source_manager"] is manager
