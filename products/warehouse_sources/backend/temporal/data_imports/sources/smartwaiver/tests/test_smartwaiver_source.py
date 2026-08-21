import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartwaiver import (
    SmartwaiverSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.source import SmartwaiverSource

# Endpoints exposing Smartwaiver's server-side `fromDts` timestamp filter.
_INCREMENTAL_ENDPOINTS = {"waivers": "createdOn", "checkins": "date"}
_FULL_REFRESH_ENDPOINTS = {"templates"}


class TestSmartwaiverSource:
    def setup_method(self):
        self.source = SmartwaiverSource()
        self.team_id = 123
        self.config = SmartwaiverSourceConfig(api_key="key")

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name, cursor_field in _INCREMENTAL_ENDPOINTS.items():
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert [f["field"] for f in schemas[name].incremental_fields] == [cursor_field]
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.source.smartwaiver_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_smartwaiver_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "waivers"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01 00:00:00"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_smartwaiver_source.assert_called_once()
        kwargs = mock_smartwaiver_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["endpoint"] == "waivers"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01 00:00:00"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartwaiver.source.smartwaiver_source"
    )
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_smartwaiver_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "templates"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01 00:00:00"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_smartwaiver_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "nope"
        with pytest.raises(ValueError, match="Unknown Smartwaiver schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
