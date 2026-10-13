from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.gitlab.source import GitLabSource


class TestGitLabSource:
    def setup_method(self):
        self.source = GitLabSource()
        self.team_id = 123
        self.config = mock.MagicMock()
        self.config.gitlab_host = "https://gitlab.com"
        self.config.personal_access_token = "glpat-token"
        self.config.project = "group/project"

    def test_connection_host_fields(self):
        assert self.source.connection_host_fields == ["gitlab_host"]

    def test_transient_5xx_error_is_retryable_not_non_retryable(self):
        # A GitLabRetryableError (any transient upstream 5xx) that exhausts fetch_page's tenacity
        # retry must stay retryable, so a GitLab-side outage doesn't disable the source.
        observed_error = "GitLab API error (retryable): status=502, url=https://gitlab.com/api/v4/projects/1/issues"
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in observed_error for key in non_retryable_errors)
        retryable_errors = self.source.get_retryable_errors()
        assert error_message_matches(observed_error, retryable_errors)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["issues"])
        assert len(schemas) == 1
        assert schemas[0].name == "issues"
