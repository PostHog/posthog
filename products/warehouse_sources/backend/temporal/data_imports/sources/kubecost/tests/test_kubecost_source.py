import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KubecostSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.kubecost import KubecostResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.source import KubecostSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestKubecostSource:
    def setup_method(self):
        self.source = KubecostSource()
        self.team_id = 123
        self.config = KubecostSourceConfig(host="https://kubecost.example.com", api_key="token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.KUBECOST

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Kubecost"
        assert config.label == "Kubecost (IBM / Apptio)"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/kubecost.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/kubecost"

        field_names = [f.name for f in config.fields]
        assert field_names == ["host", "api_key"]

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

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://kubecost.example.com/model/allocation",
            "403 Client Error: Forbidden for url: https://kubecost.example.com/model/allocation",
        ],
    )
    def test_non_retryable_errors_match_known_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        error = "500 Server Error for url: https://kubecost.example.com/model/allocation"
        assert not any(key in error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        # Every endpoint is incremental via the injected per-day window_start.
        assert all(schema.supports_incremental for schema in schemas.values())
        assert [f["field"] for f in schemas["allocation_by_namespace"].incremental_fields] == ["window_start"]
        assert schemas["assets"].incremental_fields == INCREMENTAL_FIELDS["assets"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["assets"])
        assert len(schemas) == 1
        assert schemas[0].name == "assets"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.source.validate_kubecost_credentials"
    )
    @mock.patch.object(KubecostSource, "is_database_host_valid")
    def test_validate_credentials_happy_path(self, mock_host_valid, mock_validate):
        mock_host_valid.return_value = (True, None)
        mock_validate.return_value = (True, None)

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is True
        assert error_message is None
        mock_host_valid.assert_called_once_with("kubecost.example.com", self.team_id)
        mock_validate.assert_called_once_with("https://kubecost.example.com", "token")

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

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is KubecostResumeConfig

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
