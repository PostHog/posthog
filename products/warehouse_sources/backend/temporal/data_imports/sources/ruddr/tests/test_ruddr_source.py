from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ruddr import RuddrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.source import RuddrSource


class TestRuddrSource:
    def setup_method(self) -> None:
        self.source = RuddrSource()
        self.team_id = 123
        self.config = RuddrSourceConfig(api_key="ruddr-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.source.validate_credentials")
    def test_validate_credentials_delegates_with_api_key(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in ruddr.validate_credentials; here we only assert the
        # source probes with the configured key and returns the delegate's verdict unchanged.
        mock_validate.return_value = (False, "Invalid Ruddr API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("ruddr-key")
        assert result == (False, "Invalid Ruddr API key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.source.ruddr_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "clients"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "ruddr-key"
        assert kwargs["endpoint"] == "clients"
        assert kwargs["resumable_source_manager"] is manager
