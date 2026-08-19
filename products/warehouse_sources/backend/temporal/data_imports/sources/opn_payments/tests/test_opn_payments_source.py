import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opnpayments import (
    OpnPaymentsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.opn_payments import (
    OpnPaymentsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.source import OpnPaymentsSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestOpnPaymentsSource:
    def setup_method(self):
        self.source = OpnPaymentsSource()
        self.team_id = 123
        self.config = OpnPaymentsSourceConfig(secret_key="skey_test_123")

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.OPNPAYMENTS

    def test_get_source_config(self):
        config = self.source.get_source_config

        assert config.name.value == "OpnPayments"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert not config.unreleasedSource
        assert config.iconPath == "/static/services/opn_payments.png"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["secret_key"]

    def test_secret_key_field_is_secret_password(self):
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "secret_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_lists_tables_without_credentials(self):
        assert self.source.lists_tables_without_credentials is True

    def test_default_api_version_is_supported_and_not_deprecated(self):
        assert self.source.default_version in self.source.supported_versions
        assert self.source.get_version_deprecation(self.source.default_version) is None

    def test_get_schemas(self):
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(schema.supports_incremental for schema in schemas)

    def test_incremental_schemas_advertise_their_fields(self):
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        for name in ENDPOINTS:
            assert schemas[name].incremental_fields == INCREMENTAL_FIELDS[name]

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Charges"])
        assert len(schemas) == 1
        assert schemas[0].name == "Charges"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.omise.co/charges",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://api.omise.co/charges",
            "429 Client Error: Too Many Requests",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.source.validate_opn_payments_credentials"
    )
    def test_validate_credentials_resolves_pinned_version(self, mock_validate):
        mock_validate.return_value = (True, None)

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, api_version="2019-05-29")

        assert is_valid is True
        assert error_message is None
        mock_validate.assert_called_once_with("skey_test_123", "2019-05-29")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.source.validate_opn_payments_credentials"
    )
    def test_validate_credentials_falls_back_to_default_version(self, mock_validate):
        mock_validate.return_value = (False, "Your Opn Payments secret key is invalid. Check the key and try again.")

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is False
        assert error_message == "Your Opn Payments secret key is invalid. Check the key and try again."
        mock_validate.assert_called_once_with("skey_test_123", "2019-05-29")

    def test_get_resumable_source_manager_binds_resume_config(self):
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is OpnPaymentsResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.source.opn_payments_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_opn_payments_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Charges"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.team_id = 777
        inputs.job_id = "job-1"
        inputs.api_version = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_opn_payments_source.assert_called_once()
        kwargs = mock_opn_payments_source.call_args.kwargs
        assert kwargs["secret_key"] == "skey_test_123"
        assert kwargs["endpoint"] == "Charges"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == 777
        assert kwargs["job_id"] == "job-1"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["api_version"] == "2019-05-29"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.source.opn_payments_source"
    )
    def test_source_for_pipeline_omits_last_value_on_full_refresh(self, mock_opn_payments_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Customers"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.api_version = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_opn_payments_source.call_args.kwargs["db_incremental_field_last_value"] is None
