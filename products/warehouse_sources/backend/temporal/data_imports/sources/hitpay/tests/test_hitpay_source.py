from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hitpay import HitpaySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.source import HitpaySource

_INCREMENTAL_ENDPOINTS = {"Charges"}
_FULL_REFRESH_ENDPOINTS = {"PaymentRequests", "SubscriptionPlans", "Customers", "RecurringBilling"}


class TestHitpaySource:
    def setup_method(self) -> None:
        self.source = HitpaySource()
        self.team_id = 123
        self.config = HitpaySourceConfig(api_key="key", environment="production")

    @parameterized.expand(
        [
            ("401", "401 Client Error: Unauthorized for url: https://api.hit-pay.com/v1/charges"),
            ("403", "403 Client Error: Forbidden for url: https://api.hit-pay.com/v1/charges"),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, _name: str, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.hit-pay.com/v1/charges"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.hit-pay.com/v1/charges"),
            ("timeout", "HTTPSConnectionPool(host='api.hit-pay.com', port=443): Read timed out."),
        ]
    )
    def test_non_retryable_errors_do_not_match_transient(self, _name: str, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.source.hitpay_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_hitpay_source: mock.MagicMock) -> None:
        config = HitpaySourceConfig(api_key="key", platform_api_key="platform-key", environment="sandbox")
        inputs = mock.MagicMock()
        inputs.schema_name = "Charges"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(config, manager, inputs)

        mock_hitpay_source.assert_called_once()
        kwargs = mock_hitpay_source.call_args.kwargs
        assert kwargs["api_key"] == "key"
        assert kwargs["platform_api_key"] == "platform-key"
        assert kwargs["environment"] == "sandbox"
        assert kwargs["endpoint"] == "Charges"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.source.hitpay_source")
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_hitpay_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "PaymentRequests"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_hitpay_source.call_args.kwargs["db_incremental_field_last_value"] is None

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.source.hitpay_source")
    def test_source_for_pipeline_blank_platform_key_becomes_none(self, mock_hitpay_source: mock.MagicMock) -> None:
        config = HitpaySourceConfig(api_key="key", platform_api_key="", environment="production")
        inputs = mock.MagicMock()
        inputs.schema_name = "Customers"
        inputs.should_use_incremental_field = False

        self.source.source_for_pipeline(config, mock.MagicMock(), inputs)

        assert mock_hitpay_source.call_args.kwargs["platform_api_key"] is None
