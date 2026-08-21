import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.discourse.source import DiscourseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.discourse import (
    DiscourseSourceConfig,
)


class TestDiscourseSource:
    def setup_method(self) -> None:
        self.source = DiscourseSource()
        self.team_id = 123
        self.config = DiscourseSourceConfig(
            base_url="https://forum.example.com", api_key="secret-key", api_username="system"
        )

    def test_only_posts_supports_incremental(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["posts"].supports_incremental is True
        assert [f["field"] for f in schemas["posts"].incremental_fields] == ["id"]
        for name, schema in schemas.items():
            if name != "posts":
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.discourse.source.discourse_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "posts"
        inputs.team_id = self.team_id
        inputs.job_id = "job-123"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 42
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["base_url"] == "https://forum.example.com"
        assert kwargs["api_key"] == "secret-key"
        assert kwargs["api_username"] == "system"
        assert kwargs["endpoint"] == "posts"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["job_id"] == "job-123"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 42

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "nope"
        with pytest.raises(ValueError, match="Unknown Discourse schema"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
