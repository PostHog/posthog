from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tavus import TavusSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.tavus.source import TavusSource


class TestTavusSource:
    def setup_method(self) -> None:
        self.source = TavusSource()
        self.team_id = 123
        self.config = TavusSourceConfig(api_key="tavus-key")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.tavus.source.tavus_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_tavus_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "videos"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_tavus_source.assert_called_once()
        kwargs = mock_tavus_source.call_args.kwargs
        assert kwargs["api_key"] == "tavus-key"
        assert kwargs["endpoint"] == "videos"
        assert kwargs["resumable_source_manager"] is manager
