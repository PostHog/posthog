import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SonatypeNexusSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.sonatype_nexus import (
    SonatypeNexusResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.source import SonatypeNexusSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSonatypeNexusSource:
    def setup_method(self):
        self.source = SonatypeNexusSource()
        self.team_id = 123
        self.config = SonatypeNexusSourceConfig(host="https://nexus.example.com", username="user", password="pass")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.SONATYPENEXUS

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "SonatypeNexus"
        assert config.label == "Sonatype (Nexus Repository)"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/sonatype_nexus.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/sonatype-nexus"

        field_names = [f.name for f in config.fields]
        assert field_names == ["host", "username", "password"]

    def test_password_field_is_secret_password(self):
        config = self.source.get_source_config
        password_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "password"
        )
        assert password_field.type == SourceFieldInputConfigType.PASSWORD
        assert password_field.secret is True
        assert password_field.required is True

    def test_connection_host_fields_cover_host(self):
        # The instance URL decides where the stored credentials get sent.
        assert self.source.connection_host_fields == ["host"]

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static endpoint catalog, so the public docs can render tables.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://nexus.example.com/service/rest/v1/components",
            "403 Client Error: Forbidden for url: https://nexus.example.com/service/rest/v1/tasks",
        ],
    )
    def test_non_retryable_errors_match_known_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "error",
        [
            "500 Server Error for url: https://nexus.example.com/service/rest/v1/components",
            "429 Client Error: Too Many Requests",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient_failures(self, error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in error for key in non_retryable_errors)

    def test_get_schemas_are_all_full_refresh(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # The Nexus REST API exposes no server-side timestamp filter, so nothing is incremental.
        assert all(not schema.supports_incremental for schema in schemas.values())
        assert all(not schema.supports_append for schema in schemas.values())
        assert all(schema.incremental_fields == [] for schema in schemas.values())
        # Primary keys are surfaced so the public docs' Supported tables section renders them.
        assert schemas["repositories"].detected_primary_keys == ["name"]
        assert schemas["components"].detected_primary_keys == ["repository", "id"]
        assert schemas["assets"].detected_primary_keys == ["repository", "id"]
        assert schemas["tasks"].detected_primary_keys == ["id"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["components"])
        assert len(schemas) == 1
        assert schemas[0].name == "components"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.source.validate_sonatype_nexus_credentials"
    )
    @mock.patch.object(SonatypeNexusSource, "is_database_host_valid")
    def test_validate_credentials_happy_path(self, mock_host_valid, mock_validate):
        mock_host_valid.return_value = (True, None)
        mock_validate.return_value = True

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_host_valid.assert_called_once_with("nexus.example.com", self.team_id)
        mock_validate.assert_called_once_with("https://nexus.example.com", "user", "pass")

    @mock.patch.object(SonatypeNexusSource, "is_database_host_valid")
    def test_validate_credentials_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Host is not allowed"

    def test_validate_credentials_rejects_invalid_url(self):
        config = SonatypeNexusSourceConfig(host="ftp://nope", username="user", password="pass")

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid Nexus instance URL"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.source.validate_sonatype_nexus_credentials"
    )
    @mock.patch.object(SonatypeNexusSource, "is_database_host_valid")
    def test_validate_credentials_bad_credentials(self, mock_host_valid, mock_validate):
        mock_host_valid.return_value = (True, None)
        mock_validate.return_value = False

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "Invalid Nexus credentials" in (error_message or "")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SonatypeNexusResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.source.sonatype_nexus_source"
    )
    @mock.patch.object(SonatypeNexusSource, "is_database_host_valid")
    def test_source_for_pipeline_plumbs_arguments(self, mock_host_valid, mock_source):
        mock_host_valid.return_value = (True, None)
        inputs = mock.MagicMock()
        inputs.schema_name = "components"
        inputs.team_id = self.team_id
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["host"] == "https://nexus.example.com"
        assert kwargs["username"] == "user"
        assert kwargs["password"] == "pass"
        assert kwargs["endpoint"] == "components"
        assert kwargs["resumable_source_manager"] is manager

    @mock.patch.object(SonatypeNexusSource, "is_database_host_valid")
    def test_source_for_pipeline_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")
        inputs = mock.MagicMock()
        inputs.schema_name = "components"
        inputs.team_id = self.team_id

        with pytest.raises(ValueError, match="Host is not allowed"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
