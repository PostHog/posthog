from typing import Optional

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.adyen import (
    AdyenConfigurationError,
    _require_identifier,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.settings import (
    ADYEN_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adyen.source import AdyenSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
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

    @parameterized.expand(
        [
            ("balance_platform", "Transfers", None, "ACME", "balance platform ID"),
            ("merchant_account", "SettlementDetailReports", "BP123", "  ", "merchant account"),
        ]
    )
    def test_endpoint_permissions_block_a_table_whose_identifier_is_missing(
        self,
        _name: str,
        endpoint: str,
        balance_platform: Optional[str],
        merchant_account: Optional[str],
        expected_field: str,
    ) -> None:
        config = AdyenSourceConfig(
            api_key="adyen-key",
            balance_platform=balance_platform,
            merchant_account=merchant_account,
        )

        permissions = self.source.get_endpoint_permissions(config, self.team_id, list(ENDPOINTS))

        assert expected_field in (permissions[endpoint] or "")
        assert permissions["Companies"] is None

    def test_endpoint_permissions_clear_once_both_identifiers_are_set(self) -> None:
        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, list(ENDPOINTS))

        assert permissions == dict.fromkeys(ENDPOINTS)

    def test_validate_credentials_rejects_a_table_whose_identifier_is_missing(self) -> None:
        # Rejected before any Adyen call, so an unpatched request would fail the test.
        config = AdyenSourceConfig(api_key="adyen-key", merchant_account="ACME")

        valid, error = self.source.validate_credentials(config, self.team_id, "Transfers")

        assert valid is False
        assert "balance platform ID" in (error or "")

    @parameterized.expand(
        [
            ("missing_balance_platform", None, "Balance platform ID"),
            ("missing_merchant_account", None, "Merchant account"),
            ("malformed_balance_platform", "bad id", "Balance platform ID"),
            ("malformed_merchant_account", "bad id", "Merchant account"),
        ]
    )
    def test_a_configuration_error_stops_the_job_instead_of_retrying(
        self, _name: str, value: Optional[str], label: str
    ) -> None:
        # A missing or malformed identifier is raised mid-sync; unmatched it would be captured as
        # an exception and retried by Temporal on a config only the customer can fix.
        with pytest.raises(AdyenConfigurationError) as raised:
            _require_identifier(value, label)

        assert error_message_matches(str(raised.value), self.source.get_non_retryable_errors())
