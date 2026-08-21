import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gitbook import (
    GitBookSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.source import GitBookSource


class TestGitBookSource:
    def setup_method(self) -> None:
        self.source = GitBookSource()
        self.team_id = 123
        self.config = GitBookSourceConfig(api_token="gb-token")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.source.gitbook_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "spaces"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "gb-token"
        assert kwargs["endpoint"] == "spaces"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown GitBook schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
