import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GiteaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gitea.gitea import GiteaResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gitea.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitea.source import (
    GITEA_WEBHOOK_RESOURCE_MAP,
    GiteaSource,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.gitea.source"


class TestGiteaSource:
    def setup_method(self):
        self.source = GiteaSource()
        self.team_id = 123
        self.config = GiteaSourceConfig(
            base_url="https://gitea.example.com", access_token="tok", repository="owner/repo"
        )

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GITEA

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Gitea"
        assert config.label == "Gitea"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # The scaffold shipped hidden; a finished source must be visible.
        assert config.unreleasedSource is None
        assert [f.name for f in config.fields] == ["base_url", "access_token", "repository"]

    def test_access_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "access_token"
        )
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_connection_host_fields_cover_base_url_and_repository(self):
        # `base_url` is where the token is sent; `repository` is which repo it reads. Changing
        # either must force token re-entry so a stored token can't be reused against a new target.
        assert self.source.connection_host_fields == ["base_url", "repository"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://gitea.example.com/api/v1/repos/owner/repo/issues",
            "403 Client Error: Forbidden for url: https://gitea.example.com/api/v1/repos/owner/repo/issues",
            "404 Client Error: Not Found for url: https://gitea.example.com/api/v1/repos/owner/repo",
        ],
    )
    def test_non_retryable_errors_match_known_failures(self, observed_error):
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://gitea.example.com/api/v1/repos/owner/repo/issues",
            "429 Client Error: Too Many Requests for url: https://gitea.example.com/api/v1/repos/owner/repo",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient_failures(self, other_error):
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        by_name = {schema.name: schema for schema in schemas}
        # Only the endpoints with a real server-side `since` filter are incremental.
        assert {name for name, schema in by_name.items() if schema.supports_incremental} == {"issues", "commits"}
        assert {name for name, schema in by_name.items() if schema.supports_webhooks} == {"issues", "pull_requests"}
        assert by_name["issues"].incremental_fields == INCREMENTAL_FIELDS["issues"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["issues"])
        assert [schema.name for schema in schemas] == ["issues"]

    def test_webhook_resource_map(self):
        assert GITEA_WEBHOOK_RESOURCE_MAP == {"issues": "issues", "pull_requests": "pull_request"}
        assert self.source.webhook_resource_map == GITEA_WEBHOOK_RESOURCE_MAP

    def test_webhook_template_present(self):
        template = self.source.webhook_template
        assert template is not None
        assert template.id == "template-warehouse-source-gitea"
        assert template.type == "warehouse_source_webhook"

    def test_get_desired_webhook_events_maps_schema_names(self):
        events = self.source.get_desired_webhook_events(self.config, ["issues", "pull_requests", "commits"])
        assert events == ["issues", "pull_request"]

    @mock.patch(f"{_SOURCE_MODULE}.create_repo_webhook")
    def test_create_webhook_mints_secret_and_subscribes_all_events(self, mock_create):
        self.source.create_webhook(self.config, "https://ph.example/webhook", self.team_id)

        args = mock_create.call_args.args
        assert args[:4] == ("https://gitea.example.com", "tok", "owner/repo", "https://ph.example/webhook")
        assert args[4] == ["issues", "pull_request"]
        # A fresh random secret is minted per webhook.
        assert len(args[5]) == 64

    @mock.patch(f"{_SOURCE_MODULE}.validate_gitea_credentials")
    @mock.patch.object(GiteaSource, "is_database_host_valid")
    def test_validate_credentials_happy_path(self, mock_host_valid, mock_validate):
        mock_host_valid.return_value = (True, None)
        mock_validate.return_value = (True, None)

        is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert (is_valid, error) == (True, None)
        mock_host_valid.assert_called_once_with("gitea.example.com", self.team_id)
        mock_validate.assert_called_once_with("https://gitea.example.com", "tok", "owner/repo")

    @mock.patch.object(GiteaSource, "is_database_host_valid")
    def test_validate_credentials_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")

        is_valid, error = self.source.validate_credentials(self.config, self.team_id)

        assert (is_valid, error) == (False, "Host is not allowed")

    def test_validate_credentials_rejects_invalid_url(self):
        config = GiteaSourceConfig(base_url="ftp://nope", access_token="tok", repository="owner/repo")

        is_valid, error = self.source.validate_credentials(config, self.team_id)

        assert (is_valid, error) == (False, "Invalid Gitea instance URL")

    def test_get_resumable_source_manager_binds_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is GiteaResumeConfig

    @mock.patch(f"{_SOURCE_MODULE}.gitea_source")
    @mock.patch.object(GiteaSource, "is_database_host_valid")
    def test_source_for_pipeline_plumbs_arguments(self, mock_host_valid, mock_gitea_source):
        mock_host_valid.return_value = (True, None)
        inputs = mock.MagicMock()
        inputs.schema_name = "issues"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_gitea_source.call_args.kwargs
        assert kwargs["base_url"] == "https://gitea.example.com"
        assert kwargs["access_token"] == "tok"
        assert kwargs["repository"] == "owner/repo"
        assert kwargs["endpoint"] == "issues"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"
        # Issues are webhook-capable, so the drain manager is wired in.
        assert kwargs["webhook_source_manager"] is not None

    @mock.patch(f"{_SOURCE_MODULE}.gitea_source")
    @mock.patch.object(GiteaSource, "is_database_host_valid")
    def test_source_for_pipeline_skips_webhook_manager_for_poll_only_schemas(self, mock_host_valid, mock_gitea_source):
        mock_host_valid.return_value = (True, None)
        inputs = mock.MagicMock()
        inputs.schema_name = "commits"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = False

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_gitea_source.call_args.kwargs["webhook_source_manager"] is None

    @mock.patch(f"{_SOURCE_MODULE}.gitea_source")
    @mock.patch.object(GiteaSource, "is_database_host_valid")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_host_valid, mock_gitea_source):
        mock_host_valid.return_value = (True, None)
        inputs = mock.MagicMock()
        inputs.schema_name = "pull_requests"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_gitea_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch.object(GiteaSource, "is_database_host_valid")
    def test_source_for_pipeline_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")
        inputs = mock.MagicMock()
        inputs.schema_name = "issues"
        inputs.team_id = self.team_id

        with pytest.raises(ValueError, match="Host is not allowed"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
