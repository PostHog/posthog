import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paperform import (
    PaperformSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.source import PaperformSource


class TestPaperformSource:
    def setup_method(self) -> None:
        self.source = PaperformSource()
        self.team_id = 123
        self.config = PaperformSourceConfig(api_key="pf-key")

    def test_get_schemas_only_submissions_supports_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert set(schemas) == set(ENDPOINTS)
        assert schemas["submissions"].supports_incremental is True
        assert [f["field"] for f in schemas["submissions"].incremental_fields] == ["created_at_utc"]
        # Forms and partial submissions mutate after creation, so a creation-time cursor would
        # freeze their updates — they must stay full refresh.
        assert all(
            s.supports_incremental is False and s.incremental_fields == []
            for name, s in schemas.items()
            if name != "submissions"
        )

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.paperform.source.paperform_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "submissions"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "pf-key"
        assert kwargs["endpoint"] == "submissions"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.paperform.source.paperform_source")
    def test_source_for_pipeline_drops_watermark_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "submissions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        # A full refresh must re-read everything, even when a stale watermark is still stored.
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Paperform schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
