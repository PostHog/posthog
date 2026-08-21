import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.height import HeightSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.height.source import HeightSource


class TestHeightSource:
    def setup_method(self) -> None:
        self.source = HeightSource()
        self.team_id = 123
        self.config = HeightSourceConfig(api_key="secret_key")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.height.source.height_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "users"

        self.source.source_for_pipeline(self.config, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "secret_key"
        assert kwargs["endpoint"] == "users"

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Height schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, inputs)
