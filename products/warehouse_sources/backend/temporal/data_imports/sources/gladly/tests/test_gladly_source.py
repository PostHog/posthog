import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GladlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.gladly import GladlyResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.gladly.source import GladlySource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestGladlySource:
    def setup_method(self):
        self.source = GladlySource()
        self.team_id = 123
        self.config = GladlySourceConfig(organization="myorg", agent_email="agent@x.com", api_token="token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.GLADLY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Gladly"
        assert config.label == "Gladly"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/gladly.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["organization", "agent_email", "api_token"]

    def test_api_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    def test_connection_host_fields_cover_organization(self):
        # The org subdomain decides where the stored token gets sent.
        assert self.source.connection_host_fields == ["organization"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://myorg.gladly.com/api/v1/export/jobs",
            "403 Client Error: Forbidden for url: https://myorg.gladly.com/api/v1/export/jobs/123/files/customers.jsonl",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_server_errors(self):
        non_retryable_errors = self.source.get_non_retryable_errors()
        error = "500 Server Error for url: https://myorg.gladly.com/api/v1/export/jobs"
        assert not any(key in error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Every stream carries the injected job watermark, so all are incremental.
        assert all(schema.supports_incremental for schema in schemas)
        assert all(schema.supports_append for schema in schemas)

    def test_schemas_advertise_the_injected_job_cursor(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        for schema in schemas:
            assert [f["field"] for f in schema.incremental_fields] == ["_job_updated_at"]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["customers"])
        assert len(schemas) == 1
        assert schemas[0].name == "customers"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gladly.source.validate_gladly_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message == "Invalid Gladly credentials"
        mock_validate.assert_called_once_with("myorg", "agent@x.com", "token")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.gladly.source.validate_gladly_credentials"
    )
    def test_validate_credentials_surfaces_invalid_organization(self, mock_validate):
        mock_validate.side_effect = ValueError("Invalid Gladly organization: bad org")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Invalid Gladly organization: bad org"

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is GladlyResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gladly.source.gladly_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_gladly_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "customers"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05.000Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_gladly_source.assert_called_once()
        kwargs = mock_gladly_source.call_args.kwargs
        assert kwargs["organization"] == "myorg"
        assert kwargs["agent_email"] == "agent@x.com"
        assert kwargs["api_token"] == "token"
        assert kwargs["endpoint"] == "customers"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05.000Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.gladly.source.gladly_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_gladly_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "customers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05.000Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_gladly_source.call_args.kwargs["db_incremental_field_last_value"] is None
