from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shippo import ShippoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.source import ShippoSource


class TestShippoSource:
    def setup_method(self) -> None:
        self.source = ShippoSource()
        self.team_id = 123
        self.config = ShippoSourceConfig(api_key="shippo_test_key")

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # Keys must match schema names exactly or the enrichment silently falls back to the LLM.
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.shippo.source.shippo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "shipments"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "shippo_test_key"
        assert kwargs["endpoint"] == "shipments"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.shippo.source.shippo_source")
    def test_source_for_pipeline_drops_watermark_for_full_refresh(self, mock_source: mock.MagicMock) -> None:
        # A stale watermark left on the schema must not leak into a full-refresh run.
        inputs = mock.MagicMock()
        inputs.schema_name = "shipments"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
