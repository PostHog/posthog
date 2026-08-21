import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stackoverflowforteams import (
    StackOverflowForTeamsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.source import (
    StackOverflowForTeamsSource,
)


class TestStackOverflowForTeamsSource:
    def setup_method(self):
        self.source = StackOverflowForTeamsSource()
        self.team_id = 123
        self.config = StackOverflowForTeamsSourceConfig(team="engineering", api_token="tok")

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid Stack Overflow for Teams personal access token"),
            (
                (False, 403),
                False,
                "Could not connect to Stack Overflow for Teams with the provided team name and personal access token",
            ),
            (
                (False, None),
                False,
                "Could not connect to Stack Overflow for Teams with the provided team name and personal access token",
            ),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.source.validate_stack_overflow_for_teams_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("engineering", "tok")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.source.validate_stack_overflow_for_teams_credentials"
    )
    def test_validate_credentials_surfaces_bad_team(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid Stack Overflow for Teams team name: 'a/b'.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Stack Overflow for Teams team name" in (error_message or "")
