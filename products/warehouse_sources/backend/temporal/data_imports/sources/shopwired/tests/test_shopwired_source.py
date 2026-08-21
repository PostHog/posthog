import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shopwired import (
    ShopWiredSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.source import ShopWiredSource


class TestShopWiredSource:
    def setup_method(self) -> None:
        self.source = ShopWiredSource()
        self.team_id = 123
        self.config = ShopWiredSourceConfig(api_key="sw-key", api_secret="sw-secret")

    def test_get_schemas_only_orders_supports_incremental(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        by_name = {s.name: s for s in schemas}
        assert by_name["orders"].supports_incremental is True
        assert [f["field"] for f in by_name["orders"].incremental_fields] == ["created"]
        for name, schema in by_name.items():
            if name == "orders":
                continue
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.source.shopwired_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "sw-key"
        assert kwargs["api_secret"] == "sw-secret"
        assert kwargs["endpoint"] == "orders"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown ShopWired schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
