import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    GithubAuthMethodConfig,
    GithubSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.github.source import GithubSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestGithubSource:
    def setup_method(self):
        self.source = GithubSource()
        self.team_id = 123

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GITHUB

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error",
            "403 Client Error",
            "404 Client Error",
            "Bad credentials",
            "Missing GitHub integration ID",
            "Missing personal access token",
            "GitHub access token not found",
            "Integration not found",
            "Missing integration ID",
            "This installation has been suspended",
        ],
    )
    def test_non_retryable_errors(self, expected_key):
        assert expected_key in self.source.get_non_retryable_errors()

    def test_suspended_installation_token_refresh_is_non_retryable(self):
        # The raw GitHubIntegrationError raised by refresh_access_token on a suspended installation.
        error_message = (
            'Failed to refresh installation token: {"message":"This installation has been suspended",'
            '"documentation_url":"https://docs.github.com/rest/reference/apps#create-an-installation-access-token-for-an-app",'
            '"status":"403"}'
        )
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert "This installation has been suspended" in non_retryable_errors
        assert "This installation has been suspended" in error_message

    @pytest.mark.parametrize(
        "selection,github_integration_id,personal_access_token,expected_error",
        [
            # OAuth selected but no account connected (or integration deleted) — the message
            # raised here must match a get_non_retryable_errors key so the schema stops retrying.
            ("oauth", None, "", "Missing GitHub integration ID"),
            ("pat", None, "", "Missing personal access token"),
        ],
    )
    def test_get_access_token_error_is_non_retryable(
        self, selection, github_integration_id, personal_access_token, expected_error
    ):
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(
                github_integration_id=github_integration_id,
                selection=selection,
                personal_access_token=personal_access_token,
            ),
            repository="owner/repo",
        )

        with pytest.raises(ValueError, match=expected_error):
            self.source._get_access_token(config, self.team_id)

        assert expected_error in self.source.get_non_retryable_errors()

    @pytest.mark.parametrize("endpoint", ["teams", "team_members"])
    def test_org_schemas_are_full_refresh_only(self, endpoint):
        # teams / team_members expose no timestamps, so they must never advertise incremental,
        # append, or webhook sync — otherwise the picker would offer a mode that syncs nothing.
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(github_integration_id=None, selection="pat", personal_access_token="t"),
            repository="acme/widgets",
        )
        schemas = {s.name: s for s in self.source.get_schemas(config, self.team_id)}

        assert endpoint in schemas
        schema = schemas[endpoint]
        assert schema.supports_incremental is False
        assert schema.supports_append is False
        assert schema.supports_webhooks is False
        assert schema.webhook_only is False

    def test_existing_workflow_schemas_stay_webhook_capable(self):
        # Guard that adding the org endpoints didn't disturb the webhook-capable schemas.
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(github_integration_id=None, selection="pat", personal_access_token="t"),
            repository="acme/widgets",
        )
        schemas = {s.name: s for s in self.source.get_schemas(config, self.team_id)}

        assert schemas["workflow_runs"].supports_webhooks is True
        assert schemas["workflow_jobs"].supports_webhooks is True

    def test_get_access_token_returns_pat(self):
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(
                github_integration_id=None, selection="pat", personal_access_token="github_pat_123"
            ),
            repository="owner/repo",
        )

        assert self.source._get_access_token(config, self.team_id) == "github_pat_123"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.github.source.GitHubIntegration")
    def test_get_access_token_via_oauth(self, mock_github_integration):
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(github_integration_id=42, selection="oauth", personal_access_token=""),
            repository="owner/repo",
        )

        integration = mock.MagicMock()
        integration.access_token = "gho_token"
        with mock.patch.object(self.source, "get_oauth_integration", return_value=integration):
            mock_github_integration.return_value.access_token_expired.return_value = False
            assert self.source._get_access_token(config, self.team_id) == "gho_token"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.github.source.GitHubIntegration")
    def test_get_access_token_missing_oauth_token_is_non_retryable(self, mock_github_integration):
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(github_integration_id=42, selection="oauth", personal_access_token=""),
            repository="owner/repo",
        )

        integration = mock.MagicMock()
        integration.access_token = None
        with mock.patch.object(self.source, "get_oauth_integration", return_value=integration):
            mock_github_integration.return_value.access_token_expired.return_value = False
            with pytest.raises(ValueError, match="GitHub access token not found"):
                self.source._get_access_token(config, self.team_id)

        assert "GitHub access token not found" in self.source.get_non_retryable_errors()

    @pytest.mark.parametrize(
        "selection,expected_message",
        [
            ("oauth", "No GitHub account is connected. Please reconnect your GitHub account."),
            ("pat", "GitHub personal access token is not configured. Please update the source configuration."),
        ],
    )
    def test_validate_credentials_maps_config_errors_to_friendly_message(self, selection, expected_message):
        config = GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(
                github_integration_id=None, selection=selection, personal_access_token=""
            ),
            repository="owner/repo",
        )

        valid, message = self.source.validate_credentials(config, self.team_id)

        assert valid is False
        # The wizard surfaces this string directly, so it must be the friendly copy, not the
        # internal "Missing ..." developer string raised by `_get_access_token`.
        assert message == expected_message
