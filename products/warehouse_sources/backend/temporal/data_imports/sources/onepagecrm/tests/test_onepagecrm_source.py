import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onepagecrm import (
    OnepagecrmSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.source import OnepagecrmSource


class TestOnepagecrmSource:
    def setup_method(self) -> None:
        self.source = OnepagecrmSource()
        self.team_id = 123
        self.config = OnepagecrmSourceConfig(user_id="uid-1", api_key="key-1")

    def test_get_schemas_advertises_incremental_only_where_filterable(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)
        for name, schema in schemas.items():
            if name in INCREMENTAL_FIELDS:
                assert schema.supports_incremental is True
                assert [f["field"] for f in schema.incremental_fields] == ["modified_at"]
            else:
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []
        # companies has no modified_since filter; config lists aren't filterable either.
        assert schemas["companies"].supports_incremental is False
        assert schemas["contacts"].supports_incremental is True

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.source.onepagecrm_source")
    def test_source_for_pipeline_plumbs_incremental_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "contacts"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["user_id"] == "uid-1"
        assert kwargs["api_key"] == "key-1"
        assert kwargs["endpoint"] == "contacts"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.onepagecrm.source.onepagecrm_source")
    def test_source_for_pipeline_drops_watermark_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "contacts"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown OnePageCRM schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
