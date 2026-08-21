import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.source import CalComSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.calcom import CalComSourceConfig


class TestCalComSource:
    def setup_method(self) -> None:
        self.source = CalComSource()
        self.team_id = 123
        self.config = CalComSourceConfig(api_key="cal_live_key", region="us")

    def test_only_bookings_supports_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["bookings"].supports_incremental is True
        assert [f["field"] for f in schemas["bookings"].incremental_fields] == ["updatedAt", "createdAt"]
        for name, schema in schemas.items():
            if name == "bookings":
                continue
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.source.cal_com_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "bookings"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "updatedAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "cal_live_key"
        assert kwargs["endpoint"] == "bookings"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["region"] == "us"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "updatedAt"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.source.cal_com_source")
    def test_source_for_pipeline_drops_incremental_value_when_disabled(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "bookings"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Cal.com schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
