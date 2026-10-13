import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.paystack import (
    PaystackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paystack.source import PaystackSource


class TestPaystackSource:
    def setup_method(self):
        self.source = PaystackSource()
        self.team_id = 123
        self.config = PaystackSourceConfig(secret_api_key="sk_test_x")

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Transactions"])
        assert len(schemas) == 1
        assert schemas[0].name == "Transactions"

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
