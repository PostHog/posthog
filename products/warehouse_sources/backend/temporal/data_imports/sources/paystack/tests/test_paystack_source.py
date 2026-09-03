import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paystack import (
    PaystackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paystack.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.paystack.source import PaystackSource


class TestPaystackSource:
    def setup_method(self):
        self.source = PaystackSource()
        self.team_id = 123
        self.config = PaystackSourceConfig(secret_api_key="sk_test_x")

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.paystack.co/transaction?perPage=1",
            "403 Client Error: Forbidden for url: https://api.paystack.co/customer",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_vendor_error",
        [
            "401 Client Error: Unauthorized for url: https://api.stripe.com/v1/customers",
            "500 Server Error for url: https://api.paystack.co/transaction",
        ],
    )
    def test_non_retryable_errors_does_not_match_unrelated(self, other_vendor_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_vendor_error for key in non_retryable_errors)

    def test_get_schemas_covers_all_endpoints(self):
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {schema.name for schema in schemas} == set(ENDPOINTS)

    def test_all_schemas_are_full_refresh(self):
        # Paystack exposes no verified server-side updated-at filter, so every endpoint is full refresh.
        for schema in self.source.get_schemas(self.config, self.team_id):
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Transactions"])
        assert len(schemas) == 1
        assert schemas[0].name == "Transactions"

    def test_get_schemas_filtered_unknown_name_returns_empty(self):
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Paystack secret API key"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.paystack.source.validate_paystack_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.secret_api_key)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.paystack.source.paystack_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_paystack_source):
        inputs = mock.MagicMock()
        inputs.schema_name = "Transactions"
        inputs.team_id = 456
        inputs.job_id = "job-1"
        manager = mock.MagicMock()

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        mock_paystack_source.assert_called_once()
        kwargs = mock_paystack_source.call_args.kwargs
        assert kwargs["secret_api_key"] == "sk_test_x"
        assert kwargs["endpoint"] == "Transactions"
        assert kwargs["team_id"] == 456
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert response.primary_keys == ["id"]
