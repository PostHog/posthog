import pytest
from unittest import mock

from products.warehouse_sources.backend.facade.source_config import SourceFieldInputConfig, SourceFieldInputConfigType
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kubecost import (
    KubecostSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.source import KubecostSource


class TestKubecostSource:
    def setup_method(self):
        self.source = KubecostSource()
        self.team_id = 123
        self.config = KubecostSourceConfig(host="https://kubecost.example.com", api_key="token")

    def test_api_key_field_is_optional_secret_password(self):
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        # Self-hosted Kubecost ships with no built-in auth, so the key must stay optional.
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is False

    def test_connection_host_fields_cover_host(self):
        # The API URL decides where the stored key gets sent.
        assert self.source.connection_host_fields == ["host"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["assets"])
        assert len(schemas) == 1
        assert schemas[0].name == "assets"

    @mock.patch.object(KubecostSource, "is_database_host_valid")
    def test_validate_credentials_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Host is not allowed"

    def test_validate_credentials_rejects_invalid_url(self):
        config = KubecostSourceConfig(host="ftp://nope", api_key="token")

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid Kubecost API URL"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.source.validate_kubecost_credentials"
    )
    @mock.patch.object(KubecostSource, "is_database_host_valid")
    def test_validate_credentials_bad_key(self, mock_host_valid, mock_validate):
        mock_host_valid.return_value = (True, None)
        mock_validate.return_value = (False, "Kubecost authentication failed. Please check your API key.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert "authentication failed" in (error_message or "")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.source.kubecost_source")
    @mock.patch.object(KubecostSource, "is_database_host_valid")
    def test_source_for_pipeline_plumbs_arguments(self, mock_host_valid, mock_kubecost_source):
        mock_host_valid.return_value = (True, None)
        inputs = mock.MagicMock()
        inputs.schema_name = "allocation_by_namespace"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-07-14T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_kubecost_source.assert_called_once()
        kwargs = mock_kubecost_source.call_args.kwargs
        assert kwargs["host"] == "https://kubecost.example.com"
        assert kwargs["api_key"] == "token"
        assert kwargs["endpoint"] == "allocation_by_namespace"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-07-14T00:00:00Z"

    @mock.patch.object(KubecostSource, "is_database_host_valid")
    def test_source_for_pipeline_rejects_unsafe_host(self, mock_host_valid):
        mock_host_valid.return_value = (False, "Host is not allowed")
        inputs = mock.MagicMock()
        inputs.schema_name = "assets"
        inputs.team_id = self.team_id

        with pytest.raises(ValueError, match="Host is not allowed"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
