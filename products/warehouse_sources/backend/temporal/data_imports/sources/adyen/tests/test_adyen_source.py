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

    def test_get_schemas_returns_the_whole_catalog(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(schema.description for schema in schemas)

    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_incremental_flags_track_the_endpoint_catalog(self, endpoint: str) -> None:
        schema = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}[endpoint]
        expected_fields = INCREMENTAL_FIELDS.get(endpoint, [])

        assert schema.incremental_fields == expected_fields
        assert schema.supports_incremental is bool(expected_fields)

    def test_only_endpoints_with_a_server_side_filter_are_incremental(self) -> None:
        incremental = {s.name for s in self.source.get_schemas(self.config, self.team_id) if s.supports_incremental}

        assert incremental == {"Transactions", "Transfers", "SettlementDetailReports"}

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Transfers"])

        assert [schema.name for schema in schemas] == ["Transfers"]

    def test_get_schemas_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["Nope"]) == []

    def test_schemas_list_without_credentials_for_public_docs(self) -> None:
        # The catalog is static, so the public docs endpoint can render it with a blank config.
        assert self.source.lists_tables_without_credentials is True
        blank = AdyenSourceConfig(api_key="")
        assert {schema.name for schema in self.source.get_schemas(blank, self.team_id)} == set(ENDPOINTS)

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
