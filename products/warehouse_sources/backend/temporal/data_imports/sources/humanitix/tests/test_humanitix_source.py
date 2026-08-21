import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.humanitix import (
    HumanitixSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.source import HumanitixSource


class TestHumanitixSource:
    def setup_method(self) -> None:
        self.source = HumanitixSource()
        self.team_id = 123
        self.config = HumanitixSourceConfig(api_key="hmtx-key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.humanitix.source.humanitix_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_humanitix_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_humanitix_source.assert_called_once()
        kwargs = mock_humanitix_source.call_args.kwargs
        assert kwargs["api_key"] == "hmtx-key"
        assert kwargs["endpoint"] == "events"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Humanitix schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
