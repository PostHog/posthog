import pytest
from unittest import mock

from products.warehouse_sources.sources.jira._config import JiraSourceConfig
from products.warehouse_sources.sources.jira.source import JiraSource


class TestJiraSource:
    def setup_method(self) -> None:
        self.source = JiraSource()
        self.team_id = 123
        self.config = JiraSourceConfig(subdomain="acme", email="e@x.com", api_token="token")

    def test_subdomain_is_a_connection_host_field(self) -> None:
        assert self.source.connection_host_fields == ["subdomain"]

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
    @mock.patch("products.warehouse_sources.sources.jira.source.validate_jira_credentials")
    def test_validate_credentials(
        self, mock_validate, mock_return, schema_name, expected_valid, expected_message
    ) -> None:
        mock_validate.return_value = mock_return
        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, schema_name)
        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.subdomain, self.config.email, self.config.api_token)

    @pytest.mark.parametrize(
        "pasted_site",
        ["acme.atlassian.net", "https://acme.atlassian.net", "https://acme.atlassian.net/jira/your-work", " acme "],
    )
    @mock.patch("products.warehouse_sources.sources.jira.source.validate_jira_credentials", return_value=(True, 200))
    def test_validate_credentials_accepts_pasted_site_host_or_url(self, mock_validate, pasted_site) -> None:
        config = JiraSourceConfig(subdomain=pasted_site, email="e@x.com", api_token="token")
        assert self.source.validate_credentials(config, self.team_id) == (True, None)
        mock_validate.assert_called_once()

    @pytest.mark.parametrize(
        "bad_subdomain",
        ["acme.example.com", "https://acme.atlassian.net.example.com", "https://acme.atlassian.net@example.com", ""],
    )
    @mock.patch("products.warehouse_sources.sources.jira.source.validate_jira_credentials")
    def test_validate_credentials_rejects_malformed_subdomain_without_probing(
        self, mock_validate, bad_subdomain
    ) -> None:
        config = JiraSourceConfig(subdomain=bad_subdomain, email="e@x.com", api_token="token")
        is_valid, error_message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert error_message is not None and "subdomain" in error_message
        mock_validate.assert_not_called()
