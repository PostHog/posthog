import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KustomerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.kustomer import KustomerResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.source import KustomerSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestKustomerSource:
    def setup_method(self):
        self.source = KustomerSource()
        self.team_id = 123
        self.config = KustomerSourceConfig(org_name="myorg", api_key="api-key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.KUSTOMER

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Kustomer"
        assert config.label == "Kustomer"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/kustomer.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["org_name", "api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    def test_org_name_is_a_connection_host_field(self):
        # The stored API key is sent to the host derived from org_name, so
        # retargeting it must force re-entry of the secret.
        assert self.source.connection_host_fields == ["org_name"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://myorg.api.kustomerapp.com/v1/customers",
            "403 Client Error: Forbidden for url: https://myorg.api.kustomerapp.com/v1/users",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(
            key in "500 Server Error for url: https://myorg.api.kustomerapp.com/v1/customers"
            for key in non_retryable_errors
        )

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # GET list endpoints have no updated-since filter; full refresh only.
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["customers"])
        assert len(schemas) == 1
        assert schemas[0].name == "customers"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Kustomer API credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.source.validate_kustomer_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.org_name, self.config.api_key)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is KustomerResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.source.kustomer_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_kustomer_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "customers"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_kustomer_source.assert_called_once()
        kwargs = mock_kustomer_source.call_args.kwargs
        assert kwargs["org_name"] == "myorg"
        assert kwargs["api_key"] == "api-key"
        assert kwargs["endpoint"] == "customers"
        assert kwargs["resumable_source_manager"] is manager
