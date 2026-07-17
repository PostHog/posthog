import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.env0.env0 import Env0ResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.env0.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.env0.source import Env0Source
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import Env0SourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestEnv0Source:
    def setup_method(self):
        self.source = Env0Source()
        self.team_id = 123
        self.config = Env0SourceConfig(api_key_id="key-id", api_key_secret="key-secret")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.ENV0

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Env0"
        assert config.label == "env0"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/env0.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key_id", "api_key_secret"]

    def test_api_key_secret_field_is_secret_password(self):
        config = self.source.get_source_config
        secret_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key_secret"
        )
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.env0.com/environments?limit=100",
            "403 Client Error: Forbidden for url: https://api.env0.com/projects?organizationId=org-1",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.env0.com/environments",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only deployments expose env0's server-side fromDate/toDate window.
        assert incremental == {"deployments"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["deployments"].incremental_fields == INCREMENTAL_FIELDS["deployments"]
        assert schemas["environments"].incremental_fields == []
        assert schemas["environments"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["deployments"])
        assert len(schemas) == 1
        assert schemas[0].name == "deployments"

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid env0 API key credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.env0.source.validate_env0_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.api_key_id, self.config.api_key_secret)

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is Env0ResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.env0.source.env0_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_env0_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "deployments"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_env0_source.assert_called_once()
        kwargs = mock_env0_source.call_args.kwargs
        assert kwargs["api_key_id"] == "key-id"
        assert kwargs["api_key_secret"] == "key-secret"
        assert kwargs["endpoint"] == "deployments"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.env0.source.env0_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_env0_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "environments"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_env0_source.call_args.kwargs["db_incremental_field_last_value"] is None
