import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.omni import OmniSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.omni.omni import OmniResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.omni.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.omni.source import OmniSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestOmniSource:
    def setup_method(self):
        self.source = OmniSource()
        self.team_id = 123
        self.config = OmniSourceConfig(host="https://acme.omniapp.co", api_key="omni-key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.OMNI

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Omni"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/omni.png"
        assert config.category is not None

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["host", "api_key"]

    def test_api_key_field_is_secret_password(self):
        config = self.source.get_source_config
        api_key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.secret is True
        assert api_key_field.required is True

    def test_host_field_is_not_secret(self):
        config = self.source.get_source_config
        host_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "host")
        assert host_field.type == SourceFieldInputConfigType.TEXT
        assert host_field.secret is False
        assert host_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://acme.omniapp.co/api/v1/whoami",
            "403 Client Error: Forbidden for url: https://acme.omniapp.co/api/v1/documents",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    def test_non_retryable_errors_does_not_match_unrelated_server_error(self):
        # Omni's host is customer-controlled (no fixed domain to anchor on), so the auth-failure
        # keys are necessarily generic status-line substrings — this only guards against a key so
        # broad it would also swallow a transient 5xx.
        non_retryable_errors = self.source.get_non_retryable_errors()
        other_error = "500 Server Error for url: https://acme.omniapp.co/api/v1/documents"
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, expected_incremental, expected_fields",
        [
            ("Documents", True, ["updatedAt"]),
            ("Folders", False, []),
            ("Connections", False, []),
            ("Schedules", False, []),
            ("Users", False, []),
            ("UserGroups", False, []),
        ],
    )
    def test_schemas_advertise_expected_incremental_fields(self, endpoint, expected_incremental, expected_fields):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].supports_incremental is expected_incremental
        assert schemas[endpoint].incremental_fields == INCREMENTAL_FIELDS.get(endpoint, [])
        assert [f["field"] for f in schemas[endpoint].incremental_fields] == expected_fields

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Documents"])
        assert len(schemas) == 1
        assert schemas[0].name == "Documents"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            ((True, None), True),
            ((False, "Invalid Omni API key"), False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.omni.source.validate_omni_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message
        mock_validate.assert_called_once_with(self.config.host, self.config.api_key, self.team_id, None)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.omni.source.get_omni_endpoint_permissions"
    )
    def test_get_endpoint_permissions_delegates(self, mock_get_permissions):
        mock_get_permissions.return_value = {"Users": "some reason", "Documents": None}

        result = self.source.get_endpoint_permissions(self.config, self.team_id, ["Users", "Documents"])

        assert result == {"Users": "some reason", "Documents": None}
        mock_get_permissions.assert_called_once_with(self.config.host, self.config.api_key, ["Users", "Documents"])

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OmniResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.omni.source.omni_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_omni_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Documents"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00.000Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_omni_source.assert_called_once()
        kwargs = mock_omni_source.call_args.kwargs
        assert kwargs["host"] == "https://acme.omniapp.co"
        assert kwargs["api_key"] == "omni-key"
        assert kwargs["endpoint"] == "Documents"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00.000Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.omni.source.omni_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_omni_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Documents"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00.000Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_omni_source.call_args.kwargs["db_incremental_field_last_value"] is None
