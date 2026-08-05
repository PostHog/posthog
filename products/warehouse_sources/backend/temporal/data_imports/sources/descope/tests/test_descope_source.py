import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.descope.descope import DescopeResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.descope.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.descope.source import DescopeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.descope import (
    DescopeSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestDescopeSource:
    def setup_method(self):
        self.source = DescopeSource()
        self.team_id = 123
        self.config = DescopeSourceConfig(project_id="P2abc", management_key="mgmt-key")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.DESCOPE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Descope"
        assert config.label == "Descope"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/descope.png"
        assert config.category is not None

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["project_id", "management_key"]

    def test_management_key_field_is_secret_password(self):
        config = self.source.get_source_config
        key_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "management_key"
        )
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    def test_project_id_field_is_not_secret(self):
        config = self.source.get_source_config
        project_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "project_id"
        )
        assert project_field.type == SourceFieldInputConfigType.TEXT
        assert project_field.secret is False
        assert project_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.descope.com/v1/mgmt/projects/list",
            "403 Client Error: Forbidden for url: https://api.descope.com/v2/mgmt/user/search",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.descope.com/v1/mgmt/audit/search",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "endpoint, expected_incremental, expected_fields",
        [
            ("Users", True, ["createdTime", "modifiedTime"]),
            ("Audit", True, ["occurred"]),
            ("Tenants", False, []),
            ("Roles", False, []),
            ("AccessKeys", False, []),
        ],
    )
    def test_schemas_advertise_expected_incremental_fields(self, endpoint, expected_incremental, expected_fields):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas[endpoint].supports_incremental is expected_incremental
        assert schemas[endpoint].incremental_fields == INCREMENTAL_FIELDS.get(endpoint, [])
        assert [f["field"] for f in schemas[endpoint].incremental_fields] == expected_fields

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Users"])
        assert len(schemas) == 1
        assert schemas[0].name == "Users"

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
        "products.warehouse_sources.backend.temporal.data_imports.sources.descope.source.validate_descope_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message
        mock_validate.assert_called_once_with(self.config.project_id, self.config.management_key)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is DescopeResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.descope.source.descope_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_descope_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Users"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000000
        inputs.incremental_field = "modifiedTime"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_descope_source.assert_called_once()
        kwargs = mock_descope_source.call_args.kwargs
        assert kwargs["project_id"] == "P2abc"
        assert kwargs["management_key"] == "mgmt-key"
        assert kwargs["endpoint"] == "Users"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000000
        assert kwargs["incremental_field"] == "modifiedTime"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.descope.source.descope_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_descope_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Users"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = 1700000000000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_descope_source.call_args.kwargs["db_incremental_field_last_value"] is None
