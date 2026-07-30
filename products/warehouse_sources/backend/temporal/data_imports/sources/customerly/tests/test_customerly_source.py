import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.customerly.customerly import (
    CustomerlyResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.customerly.settings import (
    CUSTOMERLY_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.customerly.source import CustomerlySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CustomerlySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCustomerlySource:
    def setup_method(self):
        self.source = CustomerlySource()
        self.team_id = 123
        self.config = CustomerlySourceConfig(access_token="token")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CUSTOMERLY

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Customerly"
        assert config.label == "Customerly"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/customerly.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["access_token"]

    def test_access_token_field_is_secret_password(self):
        config = self.source.get_source_config
        token_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "access_token"
        )
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.secret is True
        assert token_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "Customerly authentication failed: invalid or expired access token (url=https://api.customerly.io/v1/users/list)",
            "401 Client Error: Unauthorized for url: https://api.customerly.io/v1/tags",
            "403 Client Error: Forbidden for url: https://api.customerly.io/v1/leads/list",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "Customerly API error (retryable): status=503, url=https://api.customerly.io/v1/users/list",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_are_full_refresh_only(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # The Customerly API has no server-side timestamp filter, so nothing may advertise incremental.
        assert not any(schema.supports_incremental for schema in schemas)
        assert all(schema.incremental_fields == [] for schema in schemas)

    def test_get_schemas_filters_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["users", "tags"])
        assert {schema.name for schema in schemas} == {"users", "tags"}

    @pytest.mark.parametrize("is_valid", [True, False])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.customerly.source.validate_customerly_credentials"
    )
    def test_validate_credentials(self, mock_validate, is_valid):
        mock_validate.return_value = is_valid

        result, error = self.source.validate_credentials(self.config, self.team_id)

        assert result is is_valid
        assert (error is None) is is_valid
        mock_validate.assert_called_once_with("token")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CustomerlyResumeConfig

    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_for_pipeline_plumbs_schema_name(self, endpoint):
        inputs = mock.MagicMock()
        inputs.schema_name = endpoint

        response = self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert response.name == endpoint
        assert response.primary_keys == [CUSTOMERLY_ENDPOINTS[endpoint].primary_key]

    def test_documented_tables_render_without_credentials(self):
        # `lists_tables_without_credentials` feeds the public docs' Supported tables section.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {table["name"] for table in tables} == set(ENDPOINTS)
