import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.braintree.braintree import BraintreeResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.braintree.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.braintree.source import BraintreeSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BraintreeSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestBraintreeSource:
    def setup_method(self):
        self.source = BraintreeSource()
        self.team_id = 123
        self.config = BraintreeSourceConfig(environment="production", public_key="pub", private_key="priv")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.BRAINTREE

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "Braintree"
        assert config.label == "Braintree"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/braintree.png"

        field_names = [f.name for f in config.fields]
        assert field_names == ["environment", "public_key", "private_key"]

    def test_environment_field_is_a_select_with_default(self):
        config = self.source.get_source_config
        env_field = next(f for f in config.fields if f.name == "environment")
        assert isinstance(env_field, SourceFieldSelectConfig)
        assert env_field.defaultValue == "production"
        assert {option.value for option in env_field.options} == {"production", "sandbox"}

    def test_private_key_field_is_secret_password(self):
        config = self.source.get_source_config
        key_field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "private_key")
        assert key_field.type == SourceFieldInputConfigType.PASSWORD
        assert key_field.secret is True
        assert key_field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://payments.braintree-api.com/graphql",
            "401 Client Error: Unauthorized for url: https://payments.sandbox.braintree-api.com/graphql",
            "Braintree GraphQL error: User does not have permission",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://payments.braintree-api.com/graphql",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        # Every search stream supports the createdAt range filter.
        assert all(schema.supports_incremental for schema in schemas)
        assert all(schema.supports_append for schema in schemas)

    def test_schemas_advertise_created_at_cursor(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert schemas["transactions"].incremental_fields == INCREMENTAL_FIELDS["transactions"]
        assert [f["field"] for f in schemas["transactions"].incremental_fields] == ["createdAt"]

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
            (False, False, "Invalid Braintree API keys"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.braintree.source.validate_braintree_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("production", "pub", "priv")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is BraintreeResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braintree.source.braintree_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_bt_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "transactions"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_bt_source.assert_called_once()
        kwargs = mock_bt_source.call_args.kwargs
        assert kwargs["environment"] == "production"
        assert kwargs["public_key"] == "pub"
        assert kwargs["private_key"] == "priv"
        assert kwargs["endpoint"] == "transactions"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.braintree.source.braintree_source")
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_bt_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "transactions"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_bt_source.call_args.kwargs["db_incremental_field_last_value"] is None
