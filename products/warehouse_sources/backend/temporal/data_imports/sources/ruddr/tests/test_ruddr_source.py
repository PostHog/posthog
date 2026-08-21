import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ruddr import RuddrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ruddr.source import RuddrSource


class TestRuddrSource:
    def setup_method(self) -> None:
        self.source = RuddrSource()
        self.team_id = 123
        self.config = RuddrSourceConfig(api_key="ruddr-key")

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

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Ruddr schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
