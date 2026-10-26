from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stigg import StiggSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.stigg.source import StiggSource


class TestStiggSource:
    def setup_method(self) -> None:
        self.source = StiggSource()
        self.team_id = 123
        self.config = StiggSourceConfig(api_key="stigg-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.stigg.source.validate_credentials")
    def test_validate_credentials_delegates_with_api_key(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in stigg.validate_credentials; here we only assert the
        # source probes with the configured key and returns the delegate's verdict unchanged.
        mock_validate.return_value = (False, "Invalid Stigg API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("stigg-key")
        assert result == (False, "Invalid Stigg API key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.stigg.source.stigg_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "customers"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "stigg-key"
        assert kwargs["endpoint"] == "customers"
        assert kwargs["resumable_source_manager"] is manager
