import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.partnerize import (
    PartnerizeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.source import PartnerizeSource

INCREMENTAL_ENDPOINTS = {"conversions", "clicks"}


class TestPartnerizeSource:
    def setup_method(self) -> None:
        self.source = PartnerizeSource()
        self.team_id = 123
        self.config = PartnerizeSourceConfig(
            application_key="app-key", user_api_key="api-key", publisher_id="111111l92"
        )

    def test_get_schemas_incremental_flags(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        by_name = {s.name: s for s in schemas}
        for name, schema in by_name.items():
            expected = name in INCREMENTAL_ENDPOINTS
            assert schema.supports_incremental is expected
            assert schema.supports_append is expected
            assert bool(schema.incremental_fields) is expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.source.partnerize_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "conversions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-05-01 12:00:00"
        inputs.incremental_field = "conversion_time"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["application_key"] == "app-key"
        assert kwargs["user_api_key"] == "api-key"
        assert kwargs["publisher_id"] == "111111l92"
        assert kwargs["endpoint"] == "conversions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01 12:00:00"
        assert kwargs["incremental_field"] == "conversion_time"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.source.partnerize_source")
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "conversions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-05-01 12:00:00"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Partnerize schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
