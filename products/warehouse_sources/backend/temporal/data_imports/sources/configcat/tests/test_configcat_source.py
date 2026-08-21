import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.source import ConfigCatSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.configcat import (
    ConfigCatSourceConfig,
)


class TestConfigCatSource:
    def setup_method(self) -> None:
        self.source = ConfigCatSource()
        self.team_id = 123
        self.config = ConfigCatSourceConfig(basic_auth_username="user", basic_auth_password="pass")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.configcat.source.configcat_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "products"

        self.source.source_for_pipeline(self.config, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["username"] == "user"
        assert kwargs["password"] == "pass"
        assert kwargs["endpoint"] == "products"

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown ConfigCat schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, inputs)
