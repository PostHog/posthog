import pytest
from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.dockerhub import DockerhubResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.source import DockerhubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DockerhubSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestDockerhubSource:
    def setup_method(self) -> None:
        self.source = DockerhubSource()
        self.team_id = 123
        self.config = DockerhubSourceConfig(username="tom", personal_access_token="dckr_pat_token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.DOCKERHUB

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Dockerhub"
        assert config.label == "Docker Hub"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/dockerhub"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["username", "personal_access_token", "namespace"]

    def test_personal_access_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "personal_access_token"
        )
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_namespace_field_is_optional(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "namespace")
        assert field.required is False
        assert field.secret is False

    def test_namespace_is_a_connection_host_field(self) -> None:
        # The stored token pulls data from whatever namespace is configured, so changing it must force
        # secret re-entry — otherwise an editor could retarget the preserved token at another org.
        assert self.source.connection_host_fields == ["namespace"]

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["tags"])
        assert len(schemas) == 1
        assert schemas[0].name == "tags"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://hub.docker.com/v2/users/login",),
            ("403 Client Error: Forbidden for url: https://hub.docker.com/v2/namespaces/tom/repositories",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://hub.docker.com/v2/users/login",),
            ("429 Client Error: Too Many Requests for url: https://hub.docker.com/v2/namespaces/tom/repositories",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            ("blank_defaults_to_username", None, "tom"),
            ("empty_defaults_to_username", "", "tom"),
            ("whitespace_defaults_to_username", "   ", "tom"),
            ("explicit_namespace_wins", "my-org", "my-org"),
            ("explicit_namespace_is_trimmed", "  my-org  ", "my-org"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.source.validate_credentials"
    )
    def test_validate_credentials_resolves_namespace(
        self, _name: str, namespace: str | None, expected: str, mock_validate: mock.MagicMock
    ) -> None:
        mock_validate.return_value = (True, None)
        config = DockerhubSourceConfig(username="tom", personal_access_token="dckr_pat_token", namespace=namespace)
        result = self.source.validate_credentials(config, self.team_id)
        assert result == (True, None)
        mock_validate.assert_called_once_with("tom", "dckr_pat_token", expected)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DockerhubResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.dockerhub.source.dockerhub_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "repositories"
        manager = mock.MagicMock()
        config = DockerhubSourceConfig(username="tom", personal_access_token="dckr_pat_token", namespace="my-org")

        self.source.source_for_pipeline(config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["username"] == "tom"
        assert kwargs["personal_access_token"] == "dckr_pat_token"
        assert kwargs["namespace"] == "my-org"
        assert kwargs["endpoint"] == "repositories"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Docker Hub schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
