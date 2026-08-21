import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.jobnimbus import (
    JobNimbusSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.source import JobNimbusSource


class TestJobNimbusSource:
    def setup_method(self) -> None:
        self.source = JobNimbusSource()
        self.team_id = 123
        self.config = JobNimbusSourceConfig(api_key="jn-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.source.jobnimbus_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "contacts"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "jn-key"
        assert kwargs["endpoint"] == "contacts"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown JobNimbus schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
