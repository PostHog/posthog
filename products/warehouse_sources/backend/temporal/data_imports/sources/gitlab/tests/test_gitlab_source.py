import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.gitlab import GitLabResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.source import GitLabSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestGitLabSource:
    def setup_method(self):
        self.source = GitLabSource()
        self.team_id = 123
        self.config = mock.MagicMock()
        self.config.gitlab_host = "https://gitlab.com"
        self.config.personal_access_token = "glpat-token"
        self.config.project = "group/project"

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GITLAB

    def test_connection_host_fields(self):
        assert self.source.connection_host_fields == ["gitlab_host"]

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "GitLab"
        assert config.label == "GitLab"
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/gitlab.svg"

        field_names = [f.name for f in config.fields]
        assert field_names == ["gitlab_host", "personal_access_token", "project"]

        host_field, token_field, project_field = config.fields
        assert isinstance(host_field, SourceFieldInputConfig)
        assert host_field.type == SourceFieldInputConfigType.TEXT
        assert host_field.required is False
        assert host_field.secret is False

        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

        assert isinstance(project_field, SourceFieldInputConfig)
        assert project_field.required is True
        assert project_field.secret is False

    @pytest.mark.parametrize("expected_key", ["401 Client Error", "403 Client Error", "404 Client Error"])
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_returns_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, incremental",
        [
            ("issues", True),
            ("merge_requests", True),
            ("commits", True),
            ("pipelines", True),
            ("releases", False),
            ("milestones", False),
            ("branches", False),
            ("tags", False),
            ("labels", False),
            ("members", False),
        ],
    )
    def test_schema_incremental_support(self, endpoint, incremental):
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert schemas[endpoint].supports_incremental is incremental
        assert schemas[endpoint].supports_append is incremental

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["issues"])
        assert len(schemas) == 1
        assert schemas[0].name == "issues"

    def test_get_schemas_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected",
        [
            ((True, None), (True, None)),
            ((False, "Invalid GitLab personal access token"), (False, "Invalid GitLab personal access token")),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.source.validate_gitlab_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected):
        mock_validate.return_value = mock_return

        result = self.source.validate_credentials(self.config, self.team_id, schema_name="issues")

        assert result == expected
        mock_validate.assert_called_once_with(
            self.config.gitlab_host, self.config.personal_access_token, self.config.project, self.team_id
        )

    def test_get_resumable_source_manager(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is GitLabResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.source.gitlab_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_gitlab_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "issues"
        inputs.team_id = 42
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-01T00:00:00Z"
        inputs.incremental_field = "updated_at"

        manager = mock.MagicMock()
        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_gitlab_source.assert_called_once()
        kwargs = mock_gitlab_source.call_args.kwargs
        assert kwargs["host"] == "https://gitlab.com"
        assert kwargs["personal_access_token"] == "glpat-token"
        assert kwargs["project"] == "group/project"
        assert kwargs["endpoint"] == "issues"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 42
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "updated_at"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.source.gitlab_source")
    def test_source_for_pipeline_omits_last_value_when_not_incremental(self, mock_gitlab_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "branches"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "ignored"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_gitlab_source.call_args.kwargs["db_incremental_field_last_value"] is None
