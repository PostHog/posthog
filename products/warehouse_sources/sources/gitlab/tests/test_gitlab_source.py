import pytest
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

    @pytest.mark.parametrize(
        "observed_error",
        [
            # A GitLabRetryableError (any transient upstream 5xx) that exhausts fetch_page's
            # tenacity retry must stay retryable, so a GitLab-side outage doesn't disable the source.
            "GitLab API error (retryable): status=502, url=https://gitlab.com/api/v4/projects/1/issues",
            # A read timeout that exhausts both the adapter's own retries and fetch_page's tenacity
            # retry must also stay retryable — a slow/unresponsive GitLab instance, not a credential
            # or config problem the customer can fix by reconnecting.
            "HTTPSConnectionPool(host='gitlab.example.com', port=443): Max retries exceeded with url: "
            '/api/v4/projects/1/issues (Caused by ReadTimeoutError("HTTPSConnectionPool(host='
            "'gitlab.example.com', port=443): Read timed out. (read timeout=60)\"))",
        ],
    )
    def test_transient_error_is_retryable_not_non_retryable(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in observed_error for key in non_retryable_errors)
        retryable_errors = self.source.get_retryable_errors()
        assert error_message_matches(observed_error, retryable_errors)
