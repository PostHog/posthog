import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RampSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.ramp import RampResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.settings import ENDPOINTS, INCREMENTAL_FIELDS
from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.source import RampSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestRampSource:
    def setup_method(self):
        self.source = RampSource()
        self.team_id = 123
        self.config = RampSourceConfig(environment="production", client_id="cid", client_secret="sec")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.RAMP

    def test_environment_is_a_connection_host_field(self):
        # Changing environment retargets where the stored client secret is sent, so it must force
        # re-entering secrets.
        assert self.source.connection_host_fields == ["environment"]

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Ramp"
        assert config.label == "Ramp"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/ramp.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["environment", "client_id", "client_secret"]

    def test_environment_field_is_a_select_with_default(self):
        config = self.source.get_source_config
        env_field = next(f for f in config.fields if f.name == "environment")
        assert isinstance(env_field, SourceFieldSelectConfig)
        assert env_field.defaultValue == "production"
        assert {option.value for option in env_field.options} == {"production", "sandbox"}

    def test_client_secret_field_is_secret_password(self):
        config = self.source.get_source_config
        secret_field = next(
            f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "client_secret"
        )
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.ramp.com/developer/v1/token",
            "400 Client Error: Bad Request for url: https://demo-api.ramp.com/developer/v1/token",
            "403 Client Error: Forbidden for url: https://api.ramp.com/developer/v1/transactions",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://api.ramp.com/developer/v1/transactions",
            # Mid-sync 401s on data endpoints are handled by token re-mint.
            "401 Client Error: Unauthorized for url: https://api.ramp.com/developer/v1/transactions",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only transactions expose a usable server-side date filter.
        assert incremental == {"transactions"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["transactions"].incremental_fields == INCREMENTAL_FIELDS["transactions"]
        assert [f["field"] for f in schemas["transactions"].incremental_fields] == ["user_transaction_time"]
        assert schemas["users"].incremental_fields == []
        assert schemas["users"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["transactions"])
        assert len(schemas) == 1
        assert schemas[0].name == "transactions"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            ((True, None), True),
            ((False, "Ramp rejected the credentials"), False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.ramp.source.validate_ramp_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == mock_return[1]
        mock_validate.assert_called_once_with("production", "cid", "sec")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is RampResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ramp.source.ramp_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_ramp_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "transactions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_ramp_source.assert_called_once()
        kwargs = mock_ramp_source.call_args.kwargs
        assert kwargs["environment"] == "production"
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "sec"
        assert kwargs["endpoint"] == "transactions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.ramp.source.ramp_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_ramp_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "users"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_ramp_source.call_args.kwargs["db_incremental_field_last_value"] is None
