import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sonarqube import (
    SonarqubeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonarqube.source import SonarqubeSource

_INCREMENTAL_ENDPOINTS = {"issues"}
_FULL_REFRESH_ENDPOINTS = {"projects", "metrics", "rules", "users"}


class TestSonarqubeSource:
    def setup_method(self):
        self.source = SonarqubeSource()
        self.team_id = 123
        self.config = SonarqubeSourceConfig(host="https://sonar.example.com", token="tok")

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
