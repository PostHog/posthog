from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sendowl import (
    SendowlSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.source import SendowlSource


class TestSendowlSource:
    def setup_method(self) -> None:
        self.source = SendowlSource()
        self.team_id = 123
        self.config = SendowlSourceConfig(api_key="sendowl-key", api_secret="sendowl-secret")

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://www.sendowl.com/api/v1/products?page=1&per_page=50",),
            ("403 Client Error: Forbidden for url: https://www.sendowl.com/api/v1_3/orders?page=2&per_page=50",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://www.sendowl.com/api/v1/products",),
            ("HTTPSConnectionPool(host='www.sendowl.com', port=443): Read timed out.",),
            ("429 Client Error: Too Many Requests for url: https://www.sendowl.com/api/v1_3/orders",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.source.sendowl_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_sendowl_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "products"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_sendowl_source.assert_called_once()
        kwargs = mock_sendowl_source.call_args.kwargs
        assert kwargs["api_key"] == "sendowl-key"
        assert kwargs["api_secret"] == "sendowl-secret"
        assert kwargs["endpoint"] == "products"
        assert kwargs["resumable_source_manager"] is manager
