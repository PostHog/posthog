import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SonarqubeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sonarqube.settings import (
    ENDPOINTS,
    SONARQUBE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonarqube.sonarqube import SonarqubeResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sonarqube.source import SonarqubeSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

_INCREMENTAL_ENDPOINTS = {"issues"}
_FULL_REFRESH_ENDPOINTS = {"projects", "metrics", "rules", "users"}


class TestSonarqubeSource:
    def setup_method(self):
        self.source = SonarqubeSource()
        self.team_id = 123
        self.config = SonarqubeSourceConfig(host="https://sonar.example.com", token="tok")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.SONARQUBE

    def test_get_source_config_is_released_alpha(self):
        # A finished source must be visible (no unreleasedSource) and soft-labeled ALPHA.
        config = self.source.get_source_config

        assert config.name.value == "Sonarqube"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/sonarqube.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/sonarqube"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["host", "token"]

    def test_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://sonar.example.com/api/issues/search?p=1&ps=500",
            "403 Client Error: Forbidden for url: https://sonar.example.com/api/users/search?p=1&ps=500",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://sonar.example.com/api/issues/search",
            "500 Server Error: Internal Server Error for url: https://sonar.example.com/api/issues/search",
            "HTTPSConnectionPool(host='sonar.example.com', port=443): Read timed out.",
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
            assert [f["field"] for f in schemas[name].incremental_fields] == ["creationDate"]
        for name in _FULL_REFRESH_ENDPOINTS:
            assert schemas[name].supports_incremental is False
            assert schemas[name].supports_append is False
            assert schemas[name].incremental_fields == []

    def test_users_table_is_off_by_default(self):
        # /api/users/search needs Administer System; a token without it must still sync everything else.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}
        assert schemas["users"].should_sync_default is False
        assert schemas["issues"].should_sync_default is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["issues"])
        assert len(schemas) == 1
        assert schemas[0].name == "issues"

    def test_lists_tables_without_credentials_publishes_catalog(self):
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    def test_canonical_descriptions_cover_every_endpoint(self):
        canonical = self.source.get_canonical_descriptions()
        assert set(canonical) == set(SONARQUBE_ENDPOINTS)

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, 200), True, None),
            ((False, 401), False, "Invalid SonarQube token"),
            ((False, 403), False, "Could not connect to SonarQube with the provided server URL and token"),
            ((False, None), False, "Could not connect to SonarQube with the provided server URL and token"),
        ],
    )
    @mock.patch.object(SonarqubeSource, "is_database_host_valid", return_value=(True, None))
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sonarqube.source.validate_sonarqube_credentials"
    )
    def test_validate_credentials(self, mock_validate, _mock_host, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("https://sonar.example.com", "tok")

    @mock.patch.object(SonarqubeSource, "is_database_host_valid", return_value=(False, "Blocked internal host"))
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sonarqube.source.validate_sonarqube_credentials"
    )
    def test_validate_credentials_rejects_unsafe_host_without_probing(self, mock_validate, _mock_host):
        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Blocked internal host"
        mock_validate.assert_not_called()

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert manager._data_class is SonarqubeResumeConfig

    @mock.patch.object(SonarqubeSource, "is_database_host_valid", return_value=(True, None))
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sonarqube.source.sonarqube_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_sonarqube_source, _mock_host):
        inputs = mock.MagicMock()
        inputs.schema_name = "issues"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00+0000"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_sonarqube_source.assert_called_once()
        kwargs = mock_sonarqube_source.call_args.kwargs
        assert kwargs["host"] == "https://sonar.example.com"
        assert kwargs["token"] == "tok"
        assert kwargs["endpoint"] == "issues"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00+0000"

    @mock.patch.object(SonarqubeSource, "is_database_host_valid", return_value=(True, None))
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sonarqube.source.sonarqube_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_sonarqube_source, _mock_host):
        inputs = mock.MagicMock()
        inputs.schema_name = "projects"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00+0000"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_sonarqube_source.call_args.kwargs["db_incremental_field_last_value"] is None
