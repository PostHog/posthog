import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teamcity import (
    TeamcitySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.source import TeamcitySource

_INCREMENTAL_ENDPOINTS = {"builds", "changes", "test_occurrences", "problem_occurrences"}
_FULL_REFRESH_ENDPOINTS = {"projects", "build_types", "agents", "vcs_roots"}
# Occurrence fan-outs are one request per build; a first sync crawls the server's whole
# retained history, so they must stay opt-in.
_OPT_IN_ENDPOINTS = {"test_occurrences", "problem_occurrences"}


class TestTeamcitySource:
    def setup_method(self):
        self.source = TeamcitySource()
        self.team_id = 123
        self.config = TeamcitySourceConfig(host="https://teamcity.example.com", access_token="token")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid TeamCity access token"),
            ((False, 403), False, "Could not connect to TeamCity with the provided server URL and access token"),
            ((False, None), False, "Could not connect to TeamCity with the provided server URL and access token"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.source.validate_teamcity_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("https://teamcity.example.com", "token", self.team_id)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.source.validate_teamcity_credentials"
    )
    def test_validate_credentials_surfaces_bad_host(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid TeamCity server URL: 'ftp://x'.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid TeamCity server URL" in (error_message or "")
