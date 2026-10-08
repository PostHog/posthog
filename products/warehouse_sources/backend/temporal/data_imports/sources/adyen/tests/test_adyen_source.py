from typing import Optional

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.settings import (
    ADYEN_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
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

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_incremental_flags_track_the_endpoint_catalog(self, endpoint: str) -> None:
        schema = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}[endpoint]
        expected_fields = INCREMENTAL_FIELDS.get(endpoint, [])

        assert schema.incremental_fields == expected_fields
        assert schema.supports_incremental is bool(expected_fields)

    @parameterized.expand(
        [
            ("both_identifiers", "BP123", "ACME", set(ENDPOINTS)),
            (
                "platform_only",
                "BP123",
                None,
                {"Transactions", "Transfers", "AccountHolders", "BalanceAccounts", "Companies", "MerchantAccounts"},
            ),
            ("merchant_only", None, "ACME", {"SettlementDetailReports", "Companies", "MerchantAccounts"}),
            ("neither", None, "  ", {"Companies", "MerchantAccounts"}),
        ]
    )
    def test_tables_needing_a_missing_identifier_start_unselected(
        self,
        _name: str,
        balance_platform: Optional[str],
        merchant_account: Optional[str],
        expected_on: set[str],
    ) -> None:
        config = AdyenSourceConfig(
            api_key="adyen-key",
            balance_platform=balance_platform,
            merchant_account=merchant_account,
        )

        schemas = self.source.get_schemas(config, self.team_id)

        assert {schema.name for schema in schemas if schema.should_sync_default} == expected_on

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_canonical_descriptions_document_the_primary_key(self, endpoint: str) -> None:
        columns = CANONICAL_DESCRIPTIONS[endpoint]["columns"]

        for key in ADYEN_ENDPOINTS[endpoint].primary_key:
            assert key in columns

    @parameterized.expand(
        [
            ("Balance platform ID is required to sync this table.",),
            ("Merchant account is required to sync this table.",),
            ("Balance platform ID contains unsupported characters.",),
            ("Merchant account contains unsupported characters.",),
        ]
    )
    def test_non_retryable_errors_match_missing_or_malformed_identifiers(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert any(key in observed_error for key in non_retryable_errors)

    @parameterized.expand(
        [
            ("HTTPSConnectionPool(host='balanceplatform-api-live.adyen.com', port=443): Read timed out.",),
            ("500 Server Error: Internal Server Error",),
            ("Connection reset by peer",),
        ]
    )
    def test_non_retryable_errors_do_not_match_transient_errors(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()

        assert not any(key in other_error for key in non_retryable_errors)
