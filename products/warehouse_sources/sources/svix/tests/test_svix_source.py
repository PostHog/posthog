from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.sources.svix._config import SvixSourceConfig
from products.warehouse_sources.sources.svix.source import SvixSource


class TestSvixSource:
    def setup_method(self) -> None:
        self.source = SvixSource()
        self.team_id = 123
        self.config = SvixSourceConfig(api_key="sk-key")

    @mock.patch("products.warehouse_sources.sources.svix.source.svix_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "applications"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "sk-key"
        assert kwargs["endpoint"] == "applications"
        assert kwargs["resumable_source_manager"] is manager

    @parameterized.expand([("incremental", True, "2026-11-01T00:00:00Z"), ("full_refresh", False, None)])
    @mock.patch("products.warehouse_sources.sources.svix.source.svix_source")
    def test_source_for_pipeline_passes_watermark_only_when_incremental(
        self, _name: str, use_incremental: bool, expected: str | None, mock_source: mock.MagicMock
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "messages"
        inputs.should_use_incremental_field = use_incremental
        inputs.db_incremental_field_last_value = "2026-11-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] == expected

    @parameterized.expand(
        [
            ("applications", True),
            ("endpoints", True),
            ("messages", True),
            ("message_attempts", False),
            ("endpoint_stats", False),
        ]
    )
    def test_resume_covers_only_tables_that_save_state(self, schema_name: str, expected: bool) -> None:
        assert self.source.resume_covers_run(incremental_or_append=False, schema_name=schema_name) is expected
