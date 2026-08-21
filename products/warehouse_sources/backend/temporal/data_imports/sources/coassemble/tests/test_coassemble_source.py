import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.coassemble.source import CoassembleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coassemble import (
    CoassembleSourceConfig,
)


class TestCoassembleSource:
    def setup_method(self) -> None:
        self.source = CoassembleSource()
        self.team_id = 123
        self.config = CoassembleSourceConfig(workspace_id="ws-1", api_key="sk-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.coassemble.source.coassemble_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "courses"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["workspace_id"] == "ws-1"
        assert kwargs["api_key"] == "sk-key"
        assert kwargs["endpoint"] == "courses"
        assert kwargs["team_id"] is inputs.team_id
        assert kwargs["job_id"] is inputs.job_id
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Coassemble schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
