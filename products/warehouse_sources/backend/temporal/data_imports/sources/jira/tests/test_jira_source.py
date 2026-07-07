import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import JiraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jira.jira import JiraResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jira.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.jira.source import JiraSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestJiraSource:
    def setup_method(self) -> None:
        self.source = JiraSource()
        self.team_id = 123
        self.config = JiraSourceConfig(subdomain="acme", email="e@x.com", api_token="token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.JIRA

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Jira"
        assert config.label == "Jira"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/jira.svg"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["subdomain", "email", "api_token"]

    def test_api_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_subdomain_is_a_connection_host_field(self) -> None:
        assert self.source.connection_host_fields == ["subdomain"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.atlassian.net/rest/api/3/search/jql",
            "403 Client Error: Forbidden for url: https://acme.atlassian.net/rest/api/3/project/search",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "transient_error",
        [
            "500 Server Error for url: https://acme.atlassian.net/rest/api/3/search/jql",
            "429 Client Error: Too Many Requests for url: https://acme.atlassian.net/rest/api/3/search/jql",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient_failures(self, transient_error: str) -> None:
        # Rate limits and 5xx must stay retryable, not be promoted to permanent failures.
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in transient_error for key in non_retryable_errors)

    def test_get_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Only issues exposes a genuine server-side timestamp filter (JQL `updated >= ...`).
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        assert incremental == {"issues"}

    def test_incremental_schema_advertises_its_fields(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["issues"].incremental_fields == INCREMENTAL_FIELDS["issues"]
        assert schemas["projects"].incremental_fields == []
        assert schemas["projects"].supports_append is False

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["issues"])
        assert len(schemas) == 1
        assert schemas[0].name == "issues"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, schema_name, expected_valid, expected_message",
        [
            ((True, 200), None, True, None),
            ((False, 401), None, False, "Invalid Jira credentials. Check your email and API token."),
            # 403 at source-create means a valid token missing scope for the probe — accept it.
            ((False, 403), None, True, None),
            # 403 for a specific schema is a genuine access failure.
            ((False, 403), "issues", False, "Could not connect to Jira. Check your subdomain, email, and API token."),
            ((False, None), None, False, "Could not connect to Jira. Check your subdomain, email, and API token."),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jira.source.validate_jira_credentials"
    )
    def test_validate_credentials(
        self, mock_validate, mock_return, schema_name, expected_valid, expected_message
    ) -> None:
        mock_validate.return_value = mock_return
        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, schema_name)
        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.subdomain, self.config.email, self.config.api_token)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is JiraResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jira.source.jira_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_jira_source) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "issues"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "updated"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_jira_source.call_args.kwargs
        assert kwargs["subdomain"] == "acme"
        assert kwargs["email"] == "e@x.com"
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "issues"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "updated"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.jira.source.jira_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_jira_source) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "projects"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_jira_source.call_args.kwargs["db_incremental_field_last_value"] is None
