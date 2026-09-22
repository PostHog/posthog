import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gitbook import (
    GitBookSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.source import GitBookSource


class TestGitBookSource:
    def setup_method(self) -> None:
        self.source = GitBookSource()
        self.team_id = 123
        self.config = GitBookSourceConfig(api_token="gb-token")

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret API token; the base URL is hardcoded, so there is no
        # non-secret field an editor could retarget to reuse a preserved token against another host.
        assert self.source.connection_host_fields == []

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.gitbook.com/v1/orgs",),
            ("403 Client Error: Forbidden for url: https://api.gitbook.com/v1/user",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.gitbook.com/v1/orgs",),
            ("429 Client Error: Too Many Requests for url: https://api.gitbook.com/v1/user",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

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

    def test_canonical_descriptions_cover_declared_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        # Docs enrichment keys by schema name; a stray key would silently never apply.
        assert set(descriptions) == set(ENDPOINTS)
