import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wasabi import WasabiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.source import WasabiSource


class TestWasabiSource:
    def setup_method(self) -> None:
        self.source = WasabiSource()
        self.team_id = 123
        self.config = WasabiSourceConfig(api_key="wasabi-key")

    @pytest.mark.parametrize("should_use_incremental_field", [True, False])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.source.wasabi_source")
    def test_source_for_pipeline_plumbs_arguments(
        self, mock_wasabi_source: mock.MagicMock, should_use_incremental_field: bool
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "utilizations"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = should_use_incremental_field
        inputs.db_incremental_field_last_value = "2024-03-05T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_wasabi_source.call_args.kwargs
        assert kwargs["api_key"] == "wasabi-key"
        assert kwargs["endpoint"] == "utilizations"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is should_use_incremental_field
        # The watermark is only forwarded when the sync is actually incremental.
        expected_last_value = "2024-03-05T00:00:00Z" if should_use_incremental_field else None
        assert kwargs["db_incremental_field_last_value"] == expected_last_value
