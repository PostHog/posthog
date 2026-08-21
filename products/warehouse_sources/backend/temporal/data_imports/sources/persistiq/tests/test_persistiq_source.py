import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.persistiq import (
    PersistIqSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.source import PersistIqSource


class TestPersistIqSource:
    def setup_method(self) -> None:
        self.source = PersistIqSource()
        self.team_id = 123
        self.config = PersistIqSourceConfig(api_key="pq-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.persistiq.source.persistiq_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "leads"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "pq-key"
        assert kwargs["endpoint"] == "leads"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown PersistIQ schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
