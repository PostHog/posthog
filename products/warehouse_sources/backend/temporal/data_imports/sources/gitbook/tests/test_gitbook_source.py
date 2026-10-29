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

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.source.validate_credentials")
    def test_validate_credentials_delegates_to_shared_helper(self, mock_validate: mock.MagicMock) -> None:
        # The source method forwards the API token to the shared validator and returns its result verbatim.
        mock_validate.return_value = (False, "Invalid GitBook API token")
        result = self.source.validate_credentials(self.config, self.team_id)
        assert result == (False, "Invalid GitBook API token")
        mock_validate.assert_called_once_with("gb-token")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.source.gitbook_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "site_answers"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-05-01T00:00:00Z"
        inputs.incremental_field = "createdAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "gb-token"
        assert kwargs["endpoint"] == "site_answers"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-05-01T00:00:00Z"
        assert kwargs["incremental_field"] == "createdAt"
