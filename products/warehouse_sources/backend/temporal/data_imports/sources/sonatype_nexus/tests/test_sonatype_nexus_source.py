import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sonatypenexus import (
    SonatypeNexusSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sonatype_nexus.source import SonatypeNexusSource


class TestSonatypeNexusSource:
    def setup_method(self):
        self.source = SonatypeNexusSource()
        self.team_id = 123
        self.config = SonatypeNexusSourceConfig(host="https://nexus.example.com", username="user", password="pass")

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
