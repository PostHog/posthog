import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TeamcitySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.settings import (
    ENDPOINTS,
    TEAMCITY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.source import TeamcitySource
from products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.teamcity import TeamCityResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

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

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.TEAMCITY

    def test_get_source_config_ships_released(self):
        config = self.source.get_source_config

        assert config.name.value == "Teamcity"
        assert config.label == "JetBrains TeamCity"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.iconPath == "/static/services/teamcity.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/teamcity"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["host", "access_token"]

    def test_access_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "access_token"
        )
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

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

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(TEAMCITY_ENDPOINTS)

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

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is TeamCityResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.source.teamcity_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_teamcity_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "builds"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_teamcity_source.assert_called_once()
        kwargs = mock_teamcity_source.call_args.kwargs
        assert kwargs["host"] == "https://teamcity.example.com"
        assert kwargs["access_token"] == "token"
        assert kwargs["endpoint"] == "builds"
        assert kwargs["team_id"] == self.team_id
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.source.teamcity_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_teamcity_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "projects"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_teamcity_source.call_args.kwargs["db_incremental_field_last_value"] is None
