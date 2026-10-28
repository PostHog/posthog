from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.migration.catalog import (
    MatchConfidence,
    TableMatch,
    match_destination,
    match_source,
    match_tables,
    posthog_tables,
    prefill_config,
)
from products.warehouse_sources.backend.migration.catalog.fivetran import SOURCE_OVERRIDES
from products.warehouse_sources.backend.models.external_data_destination import ExternalDataDestination
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType as T


class TestCatalog:
    def test_every_source_override_is_a_registered_source(self) -> None:
        registered = set(SourceRegistry.get_all_sources())
        assert {service: str(t) for service, t in SOURCE_OVERRIDES.items() if t not in registered} == {}

    @parameterized.expand(
        [
            ("name_match", "fivetran", "google_ads", T.GOOGLEADS),
            ("managed_database_flavor", "fivetran", "postgres_rds", T.POSTGRES),
            ("override_beats_name_match", "fivetran", "confluent_cloud", T.KAFKA),
            ("rejected_name_match", "fivetran", "segment", None),
            ("unknown_service", "fivetran", "not_a_service", None),
            ("unknown_provider", "airbyte", "postgres", None),
        ]
    )
    def test_match_source(self, _name: str, provider: str, service: str, expected: T | None) -> None:
        assert match_source(provider, service) == expected

    @parameterized.expand(
        [
            ("bigquery_variant", "fivetran", "managed_big_query", ExternalDataDestination.Type.BIGQUERY),
            ("lake_with_unknown_storage", "fivetran", "managed_data_lake", None),
            ("unknown_provider", "airbyte", "snowflake", None),
        ]
    )
    def test_match_destination(
        self, _name: str, provider: str, service: str, expected: ExternalDataDestination.Type | None
    ) -> None:
        assert match_destination(provider, service) == expected

    @parameterized.expand(
        [
            ("same_name", "tickets", "tickets", MatchConfidence.EXACT),
            ("case_and_separators", "balance_transaction", "BalanceTransaction", MatchConfidence.EXACT),
            ("plural", "contact", "contacts", MatchConfidence.INFERRED),
            ("plural_ies", "category", "categories", MatchConfidence.INFERRED),
            ("history_suffix", "campaign_history", "campaigns", MatchConfidence.INFERRED),
            (
                "daily_report_suffix",
                "campaign_performance_daily_report",
                "campaign_performance_report",
                MatchConfidence.INFERRED,
            ),
            ("no_match", "person", None, None),
        ]
    )
    def test_match_tables(
        self, _name: str, vendor_table: str, posthog_table: str | None, confidence: MatchConfidence | None
    ) -> None:
        candidates = {
            "tickets",
            "BalanceTransaction",
            "contacts",
            "categories",
            "campaigns",
            "campaign_performance_report",
        }
        assert match_tables("fivetran", [vendor_table], candidates) == (
            TableMatch(vendor_table=vendor_table, posthog_table=posthog_table, confidence=confidence),
        )

    def test_exact_match_wins_over_an_inferred_one(self) -> None:
        (match,) = match_tables("fivetran", ["campaign_history"], {"campaign_history", "campaigns"})
        assert (match.posthog_table, match.confidence) == ("campaign_history", MatchConfidence.EXACT)

    @parameterized.expand(
        [
            ("lists_tables_without_credentials", T.STRIPE, "Charge"),
            ("needs_credentials_to_list", T.GOOGLEADS, "campaign"),
        ]
    )
    def test_posthog_tables(self, _name: str, source_type: T, expected_table: str) -> None:
        tables = posthog_tables(source_type)
        assert tables is not None and expected_table in tables

    def test_posthog_tables_is_none_for_user_defined_tables(self) -> None:
        assert posthog_tables(T.POSTGRES) is None

    @parameterized.expand(
        [
            (
                "same_name_and_tunnel",
                T.POSTGRES,
                {"host": "db.example.com", "port": 5432, "user": "reader", "password": "******", "tunnel_user": "jump"},
                {"host": "db.example.com", "port": 5432, "user": "reader", "ssh_tunnel.auth.username": "jump"},
            ),
            (
                "renamed_nested_field",
                T.SNOWFLAKE,
                {"database": "analytics", "user": "reader", "role": ""},
                {"database": "analytics", "auth_type.user": "reader"},
            ),
            ("no_tunnel_field", T.STRIPE, {"tunnel_host": "jump.example.com"}, {}),
        ]
    )
    def test_prefill_config(
        self, _name: str, source_type: T, vendor_config: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        assert prefill_config("fivetran", source_type, vendor_config) == expected
