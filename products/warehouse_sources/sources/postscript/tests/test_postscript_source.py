from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.postscript import (
    PostscriptSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postscript.source import PostscriptSource


class TestPostscriptSource:
    def setup_method(self) -> None:
        self.source = PostscriptSource()
        self.team_id = 123
        self.config = PostscriptSourceConfig(api_key="sk_postscript")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.postscript.source.postscript_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_postscript_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "subscribers"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.api_version = None
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "updated_at"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_postscript_source.call_args.kwargs
        assert kwargs["api_key"] == "sk_postscript"
        assert kwargs["endpoint"] == "subscribers"
        assert kwargs["api_version"] == "v2"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["incremental_field"] == "updated_at"
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.postscript.source.postscript_source")
    def test_source_for_pipeline_omits_watermark_when_not_incremental(
        self, mock_postscript_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "subscribers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_postscript_source.call_args.kwargs["db_incremental_field_last_value"] is None
