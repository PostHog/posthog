import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.checkout_com import (
    CheckoutComResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.source import CheckoutComSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CheckoutComSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestCheckoutComSource:
    def setup_method(self):
        self.source = CheckoutComSource()
        self.team_id = 123
        self.config = CheckoutComSourceConfig(environment="production", client_id="ack_id", client_secret="secret")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.CHECKOUTCOM

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "CheckoutCom"
        assert config.label == "Checkout.com"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/checkout_com.png"

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
            "401 Client Error: Unauthorized for url: https://access.checkout.com/connect/token",
            "400 Client Error: Bad Request for url: https://access.sandbox.checkout.com/connect/token",
            "403 Client Error: Forbidden for url: https://api.checkout.com/disputes?limit=250",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://api.checkout.com/disputes",
            # Mid-sync 401s on the API host are handled by token re-mint.
            "401 Client Error: Unauthorized for url: https://api.checkout.com/disputes",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert [s.name for s in schemas] == ["disputes"]
        assert all(schema.supports_incremental for schema in schemas)
        assert [f["field"] for f in schemas[0].incremental_fields] == ["last_update"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Checkout.com access keys"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.source.validate_checkout_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("production", "ack_id", "secret")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is CheckoutComResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.source.checkout_com_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_co_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "disputes"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_co_source.assert_called_once()
        kwargs = mock_co_source.call_args.kwargs
        assert kwargs["environment"] == "production"
        assert kwargs["client_id"] == "ack_id"
        assert kwargs["client_secret"] == "secret"
        assert kwargs["endpoint"] == "disputes"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-01-02T03:04:05Z"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.source.checkout_com_source"
    )
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_co_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "disputes"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-01-02T03:04:05Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_co_source.call_args.kwargs["db_incremental_field_last_value"] is None
