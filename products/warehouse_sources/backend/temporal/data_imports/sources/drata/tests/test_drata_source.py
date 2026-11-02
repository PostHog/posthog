from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.drata.source import DrataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.drata import DrataSourceConfig


class TestDrataSource:
    def setup_method(self) -> None:
        self.source = DrataSource()
        self.team_id = 123
        self.config = DrataSourceConfig(api_key="drata_key", region="EU")

    @parameterized.expand(
        [
            ("412 Client Error: Precondition Failed for url: https://public-api.apac.drata.com/public/v2/events",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures_in_every_region(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.drata.source.drata_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "createdAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "drata_key"
        assert kwargs["region"] == "EU"
        assert kwargs["endpoint"] == "events"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "createdAt"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.drata.source.drata_source")
    def test_source_for_pipeline_drops_incremental_value_when_disabled(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "events"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
