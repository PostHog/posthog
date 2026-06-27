import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PlaidSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plaid.plaid import PlaidResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.plaid.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plaid.source import PlaidSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPlaidSource:
    def setup_method(self):
        self.source = PlaidSource()
        self.team_id = 123
        self.config = PlaidSourceConfig(environment="production", client_id="cid", secret="sec", access_token="tok")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.PLAID

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Plaid"
        assert config.label == "Plaid"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/plaid.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["environment", "client_id", "secret", "access_token"]

    def test_environment_field_is_a_select_with_default(self):
        config = self.source.get_source_config
        env_field = next(f for f in config.fields if f.name == "environment")
        assert isinstance(env_field, SourceFieldSelectConfig)
        assert env_field.defaultValue == "production"
        assert {option.value for option in env_field.options} == {"production", "sandbox"}

    @pytest.mark.parametrize("field_name", ["secret", "access_token"])
    def test_secret_fields_are_secret_passwords(self, field_name):
        config = self.source.get_source_config
        secret_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == field_name)
        assert secret_field.type == SourceFieldInputConfigType.PASSWORD
        assert secret_field.secret is True
        assert secret_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://production.plaid.com/transactions/get",
            "400 Client Error: Bad Request for url: https://sandbox.plaid.com/accounts/get",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://production.plaid.com/transactions/get",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        incremental = {schema.name for schema in schemas if schema.supports_incremental}
        # Only transactions have a server-side date filter.
        assert incremental == {"transactions"}

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["transactions"].incremental_fields == INCREMENTAL_FIELDS["transactions"]
        assert [f["field"] for f in schemas["transactions"].incremental_fields] == ["date"]
        assert schemas["accounts"].incremental_fields == []
        assert schemas["accounts"].supports_append is False

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["transactions"])
        assert len(schemas) == 1
        assert schemas[0].name == "transactions"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Plaid credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.plaid.source.validate_plaid_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("production", "cid", "sec", "tok")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PlaidResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.plaid.source.plaid_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_plaid_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "transactions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-05-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_plaid_source.assert_called_once()
        kwargs = mock_plaid_source.call_args.kwargs
        assert kwargs["environment"] == "production"
        assert kwargs["client_id"] == "cid"
        assert kwargs["secret"] == "sec"
        assert kwargs["access_token"] == "tok"
        assert kwargs["endpoint"] == "transactions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-05-01"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.plaid.source.plaid_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_plaid_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "accounts"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-05-01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_plaid_source.call_args.kwargs["db_incremental_field_last_value"] is None
