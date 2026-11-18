from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.migration.catalog import (
    MatchConfidence,
    PostHogTables,
    TableMatch,
    match_source,
    match_tables,
    posthog_tables,
    prefill_config,
)
from products.warehouse_sources.backend.migration.catalog.fivetran import SOURCE_OVERRIDES
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType as T


class TestCatalog:
    def test_every_source_override_is_a_registered_source(self) -> None:
        registered = set(SourceRegistry.get_all_sources())
        assert {service: str(t) for service, t in SOURCE_OVERRIDES.items() if t not in registered} == {}

    @parameterized.expand(
        [
            ("name_match", "fivetran", "google_ads", T.GOOGLEADS),
            ("override_beats_name_match", "fivetran", "confluent_cloud", T.KAFKA),
            ("rejected_name_match", "fivetran", "segment", None),
        ]
    )
    def test_match_source(self, _name: str, provider: str, service: str, expected: T | None) -> None:
        assert match_source(provider, service) == expected

    @parameterized.expand(
        [
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
        ]
    )
    def test_match_tables(
        self, _name: str, vendor_table: str, posthog_table: str | None, confidence: MatchConfidence | None
    ) -> None:
        candidates = {
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

    def test_inferred_match_skips_a_table_another_vendor_table_matches_exactly(self) -> None:
        assert match_tables("fivetran", ["account", "account_history"], {"Account"}) == (
            TableMatch(vendor_table="account", posthog_table="Account", confidence=MatchConfidence.EXACT),
            TableMatch(vendor_table="account_history", posthog_table=None, confidence=None),
        )

    @parameterized.expand(
        [
            ("plural_listed_first", ["campaign", "campaign_history"]),
            ("history_listed_first", ["campaign_history", "campaign"]),
        ]
    )
    def test_closer_name_keeps_a_posthog_table_two_vendor_tables_infer(
        self, _name: str, vendor_tables: list[str]
    ) -> None:
        matches = {
            m.vendor_table: (m.posthog_table, m.confidence)
            for m in match_tables("fivetran", vendor_tables, {"campaigns"})
        }
        assert matches == {"campaign": ("campaigns", MatchConfidence.INFERRED), "campaign_history": (None, None)}

    @parameterized.expand(
        [
            ("static_catalog", T.STRIPE, "Charge", True),
            ("needs_config_to_list", T.GITHUB, "issues", False),
            ("also_discovers_tables", T.FIREBASE, "auth_users", False),
        ]
    )
    def test_posthog_tables(self, _name: str, source_type: T, known_table: str, complete: bool) -> None:
        tables = posthog_tables(source_type)
        assert isinstance(tables, PostHogTables)
        assert (known_table in tables.names, tables.complete) == (True, complete)

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
