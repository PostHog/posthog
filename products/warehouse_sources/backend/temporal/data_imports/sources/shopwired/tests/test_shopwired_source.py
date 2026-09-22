import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.shopwired import (
    ShopWiredSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.source import ShopWiredSource


class TestShopWiredSource:
    def setup_method(self) -> None:
        self.source = ShopWiredSource()
        self.team_id = 123
        self.config = ShopWiredSourceConfig(api_key="sw-key", api_secret="sw-secret")

    def test_no_connection_host_fields(self) -> None:
        # Both fields are secrets and the base URL is hardcoded, so there is no non-secret field an
        # editor could retarget to reuse preserved credentials against another host.
        assert self.source.connection_host_fields == []

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.ecommerceapi.uk/v1/orders?count=100",
            ),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.ecommerceapi.uk/v1/products?count=100"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.ecommerceapi.uk/v1/orders"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.ecommerceapi.uk/v1/products"),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.source.validate_credentials"
    )
    def test_validate_credentials_delegates_with_credentials(self, mock_validate: mock.MagicMock) -> None:
        # The status-to-message mapping lives in shopwired.validate_credentials; here we only assert the
        # source probes with the configured credentials and returns the delegate's verdict unchanged.
        mock_validate.return_value = (False, "Invalid ShopWired API key or secret")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("sw-key", "sw-secret")
        assert result == (False, "Invalid ShopWired API key or secret")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.shopwired.source.shopwired_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "orders"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "sw-key"
        assert kwargs["api_secret"] == "sw-secret"
        assert kwargs["endpoint"] == "orders"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown ShopWired schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
