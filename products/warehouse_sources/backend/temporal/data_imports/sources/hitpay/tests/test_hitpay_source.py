from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hitpay import HitpaySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hitpay.source import HitpaySource

_INCREMENTAL_ENDPOINTS = {"Charges"}
_FULL_REFRESH_ENDPOINTS = {"PaymentRequests", "SubscriptionPlans", "Customers", "RecurringBilling"}


class TestHitpaySource:
    def setup_method(self) -> None:
        self.source = HitpaySource()
        self.team_id = 123
        self.config = HitpaySourceConfig(api_key="key", environment="production")

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

    def test_source_for_pipeline_blank_platform_key_becomes_none(self) -> None:
        config = HitpaySourceConfig(api_key="key", platform_api_key="", environment="production")
        result = SourceDriver(self.source, config).run(
            "Customers", [ScriptedResponse(json={"data": [], "meta": {"last_page": 1}})]
        )

        assert result.raised is None
        assert result.paths == ["/v1/customers"]
        assert "x-platform-key" not in result.requests[0].headers
        assert result.session_options[0]["redact_values"] == ("key",)
