from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.secoda import SecodaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.secoda.source import SecodaSource


class TestSecodaSource:
    def setup_method(self) -> None:
        self.source = SecodaSource()
        self.team_id = 123
        self.config = SecodaSourceConfig(api_key="sk-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.secoda.source.validate_credentials")
    def test_validate_credentials_delegates_to_shared_helper(self, mock_validate: mock.MagicMock) -> None:
        # The source method forwards the workspace API key to the shared validator and returns its result verbatim.
        mock_validate.return_value = (False, "Invalid Secoda API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        assert result == (False, "Invalid Secoda API key")
        mock_validate.assert_called_once_with("sk-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.secoda.source.secoda_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "tables"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "sk-key"
        assert kwargs["endpoint"] == "tables"
        assert kwargs["resumable_source_manager"] is manager
