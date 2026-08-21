import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.qualaroo import (
    QualarooSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.source import QualarooSource


class TestQualarooSource:
    def setup_method(self) -> None:
        self.source = QualarooSource()
        self.team_id = 123
        self.config = QualarooSourceConfig(api_key="q-key", api_secret="q-secret")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.source.qualaroo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "nudges"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "q-key"
        assert kwargs["api_secret"] == "q-secret"
        assert kwargs["endpoint"] == "nudges"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Qualaroo schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
