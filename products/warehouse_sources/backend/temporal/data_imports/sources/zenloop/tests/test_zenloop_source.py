from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zenloop import (
    ZenloopSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.source import ZenloopSource


class TestZenloopSource:
    def setup_method(self) -> None:
        self.source = ZenloopSource()
        self.team_id = 123
        self.config = ZenloopSourceConfig(api_token="zenloop-token")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.zenloop.source.zenloop_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_zenloop_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "surveys"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_zenloop_source.assert_called_once()
        kwargs = mock_zenloop_source.call_args.kwargs
        assert kwargs["api_token"] == "zenloop-token"
        assert kwargs["endpoint"] == "surveys"
        assert kwargs["resumable_source_manager"] is manager
