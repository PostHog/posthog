from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sendowl import (
    SendowlSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.source import SendowlSource


class TestSendowlSource:
    def setup_method(self) -> None:
        self.source = SendowlSource()
        self.team_id = 123
        self.config = SendowlSourceConfig(api_key="sendowl-key", api_secret="sendowl-secret")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.source.sendowl_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_sendowl_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "products"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_sendowl_source.assert_called_once()
        kwargs = mock_sendowl_source.call_args.kwargs
        assert kwargs["api_key"] == "sendowl-key"
        assert kwargs["api_secret"] == "sendowl-secret"
        assert kwargs["endpoint"] == "products"
        assert kwargs["resumable_source_manager"] is manager
