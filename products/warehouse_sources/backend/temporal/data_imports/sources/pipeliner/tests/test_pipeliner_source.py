import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pipeliner import (
    PipelinerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.source import PipelinerSource


class TestPipelinerSource:
    def setup_method(self):
        self.source = PipelinerSource()
        self.team_id = 123
        self.config = PipelinerSourceConfig(
            service_url="us-east.api.pipelinersales.com",
            space_id="space-1",
            username="api-user",
            password="api-pass",
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.source.pipeliner_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_pipeliner_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "opportunities"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01 00:00:00"
        inputs.incremental_field = "modified"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_pipeliner_source.call_args.kwargs
        assert kwargs["service_url"] == "us-east.api.pipelinersales.com"
        assert kwargs["space_id"] == "space-1"
        assert kwargs["username"] == "api-user"
        assert kwargs["password"] == "api-pass"
        assert kwargs["endpoint"] == "opportunities"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01 00:00:00"
        assert kwargs["incremental_field"] == "modified"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.source.pipeliner_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_pipeliner_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "accounts"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_pipeliner_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "unknown"

        with pytest.raises(ValueError, match="Unknown Pipeliner schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
