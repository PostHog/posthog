import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.jira import JiraSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.jira.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.jira.source import JiraSource


class TestJiraSource:
    def setup_method(self) -> None:
        self.source = JiraSource()
        self.team_id = 123
        self.config = JiraSourceConfig(subdomain="acme", email="e@x.com", api_token="token")

    def test_get_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Only issues exposes a genuine server-side timestamp filter (JQL `updated >= ...`).
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        assert incremental == {"issues"}

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

    @pytest.mark.parametrize(
        "bad_subdomain",
        ["acme.atlassian.net", "https://acme.atlassian.net", "acme.example.com", ""],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.jira.source.validate_jira_credentials"
    )
    def test_validate_credentials_rejects_malformed_subdomain_without_probing(
        self, mock_validate, bad_subdomain
    ) -> None:
        config = JiraSourceConfig(subdomain=bad_subdomain, email="e@x.com", api_token="token")
        is_valid, error_message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert error_message is not None and "subdomain" in error_message
        mock_validate.assert_not_called()
