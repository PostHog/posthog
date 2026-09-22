import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stackoverflowforteams import (
    StackOverflowForTeamsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.stack_overflow_for_teams.source import (
    StackOverflowForTeamsSource,
)


class TestStackOverflowForTeamsSource:
    def setup_method(self):
        self.source = StackOverflowForTeamsSource()
        self.team_id = 123
        self.config = StackOverflowForTeamsSourceConfig(team="engineering", api_token="tok")

    def test_team_listed_as_connection_host_field(self):
        # The PAT is sent to api.stackoverflowteams.com/v3/teams/<team>, so retargeting the
        # team must re-require it.
        assert self.source.connection_host_fields == ["team"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stackoverflowteams.com/v3/teams/engineering/questions",
            "403 Client Error: Forbidden for url: https://api.stackoverflowteams.com/v3/teams/engineering/articles",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.stackoverflowteams.com/v3/teams/engineering/questions",
            "500 Server Error: Internal Server Error for url: https://api.stackoverflowteams.com/v3/teams/engineering/questions",
            "HTTPSConnectionPool(host='api.stackoverflowteams.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_all_full_refresh(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in ENDPOINTS:
            # No verified server-side timestamp filter on any v3 list endpoint yet - every
            # table ships full refresh.
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) - the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

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
