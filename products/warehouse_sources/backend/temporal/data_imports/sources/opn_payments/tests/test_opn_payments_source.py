import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.opnpayments import (
    OpnPaymentsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.opn_payments.source import OpnPaymentsSource


class TestOpnPaymentsSource:
    def setup_method(self):
        self.source = OpnPaymentsSource()
        self.team_id = 123
        self.config = OpnPaymentsSourceConfig(secret_key="skey_test_123")

    def test_default_api_version_is_supported_and_not_deprecated(self):
        assert self.source.default_version in self.source.supported_versions
        assert self.source.get_version_deprecation(self.source.default_version) is None

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.omise.co/charges",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

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
