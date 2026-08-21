from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.source import AdyenSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adyen import AdyenSourceConfig

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.adyen.source"


class TestAdyenSource:
    def setup_method(self) -> None:
        self.source = AdyenSource()
        self.team_id = 123
        self.config = AdyenSourceConfig(
            api_key="adyen-key",
            environment="live",
            balance_platform="BP123",
            merchant_account="ACME",
            start_date="2026-01-01",
            settlement_report_start_batch=None,
        )

    def test_only_endpoints_with_a_server_side_filter_are_incremental(self) -> None:
        incremental = {s.name for s in self.source.get_schemas(self.config, self.team_id) if s.supports_incremental}

        assert incremental == {"Transactions", "Transfers", "SettlementDetailReports"}
