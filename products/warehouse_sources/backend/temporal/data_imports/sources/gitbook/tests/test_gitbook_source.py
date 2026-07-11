import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GitBookSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.gitbook import GitBookResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gitbook.source import GitBookSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestGitBookSource:
    def setup_method(self) -> None:
        self.source = GitBookSource()
        self.team_id = 123
        self.config = GitBookSourceConfig(api_token="gb-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.GITBOOK

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "GitBook"
        assert config.label == "GitBook"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/gitbook"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token"]

    def test_api_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret API token; the base URL is hardcoded, so there is no
        # non-secret field an editor could retarget to reuse a preserved token against another host.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["spaces"])
        assert len(schemas) == 1
        assert schemas[0].name == "spaces"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

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

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is GitBookResumeConfig

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
