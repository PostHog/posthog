import pytest
from unittest import mock

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WorkOSSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.source import WorkOSSource
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.workos import WorkOSResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestWorkOSSource:
    def setup_method(self):
        self.source = WorkOSSource()
        self.team_id = 123
        self.config = WorkOSSourceConfig(api_key="sk_test_123")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.WORKOS

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "WorkOS"
        assert config.label == "WorkOS"
        assert config.iconPath == "/static/services/workos.png"
        assert len(config.fields) == 1

        api_key_field = config.fields[0]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.name == "api_key"
        assert api_key_field.type == SourceFieldInputConfigType.PASSWORD
        assert api_key_field.required is True
        assert api_key_field.secret is True

    @pytest.mark.parametrize(
        "expected_key",
        [
            "401 Client Error: Unauthorized for url: https://api.workos.com",
            "403 Client Error: Forbidden for url: https://api.workos.com",
            "422 Client Error: Unprocessable Entity for url: https://api.workos.com",
        ],
    )
    def test_non_retryable_errors_includes_workos_key(self, expected_key):
        errors = self.source.get_non_retryable_errors()
        assert expected_key in errors

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.workos.com/organizations?limit=100",
            "422 Client Error: Unprocessable Entity for url: https://api.workos.com/directory_users?limit=100&order=desc",
        ],
    )
    def test_non_retryable_errors_matches_observed_error_message(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "401 Client Error: Unauthorized for url: https://api.clerk.com/v1/users",
        ],
    )
    def test_non_retryable_errors_does_not_match_other_vendors(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        schema_names = {schema.name for schema in schemas}
        assert schema_names == set(ENDPOINTS)
        assert all(not schema.supports_incremental for schema in schemas)
        assert all(not schema.supports_append for schema in schemas)

    def test_get_schemas_filtered_by_names(self):
        first_endpoint = next(iter(ENDPOINTS))
        schemas = self.source.get_schemas(self.config, self.team_id, names=[first_endpoint])

        assert len(schemas) == 1
        assert schemas[0].name == first_endpoint

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["nonexistent"])
        assert schemas == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            ((True, None), True, None),
            ((False, "Invalid WorkOS credentials"), False, "Invalid WorkOS credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.workos.source.validate_workos_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        inputs.team_id = self.team_id
        inputs.job_id = "job_1"
        inputs.logger = mock.MagicMock()

        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is WorkOSResumeConfig
