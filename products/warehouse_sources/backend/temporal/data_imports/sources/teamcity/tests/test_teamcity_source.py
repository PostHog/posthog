import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teamcity import (
    TeamcitySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.settings import ENDPOINTS
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
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://teamcity.example.com/app/rest/builds?locator=count:100",
            "403 Client Error: Forbidden for url: https://teamcity.example.com/app/rest/agents?locator=count:100",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://teamcity.example.com/app/rest/builds",
            "500 Server Error: Internal Server Error for url: https://teamcity.example.com/app/rest/builds",
            "HTTPSConnectionPool(host='teamcity.example.com', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_match_endpoints_with_correct_sync_modes(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name in _INCREMENTAL_ENDPOINTS:
            assert schemas[name].supports_incremental is True
            assert schemas[name].supports_append is True
            assert len(schemas[name].incremental_fields) == 1
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].incremental_fields == []
        for name in ENDPOINTS:
            assert schemas[name].should_sync_default is (name not in _OPT_IN_ENDPOINTS)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["builds", "nope"])
        assert [s.name for s in schemas] == ["builds"]

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

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
