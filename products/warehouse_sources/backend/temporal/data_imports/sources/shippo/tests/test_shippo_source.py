import pytest
from unittest import mock

from parameterized import parameterized

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

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["transactions"])
        assert len(schemas) == 1
        assert schemas[0].name == "transactions"

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # Keys must match schema names exactly or the enrichment silently falls back to the LLM.
        assert set(CANONICAL_DESCRIPTIONS) == set(ENDPOINTS)

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.goshippo.com/shipments/?results=100",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.goshippo.com/transactions/?results=100",
            ),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.goshippo.com/shipments/"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.goshippo.com/shipments/"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

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

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Shippo schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
