from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.migration.cost import (
    Confidence,
    CostedConnection,
    CostEstimate,
    PriceTier,
    ReportedUsage,
    estimate_cost,
)
from products.warehouse_sources.backend.migration.pricing import _paid_plan_tiers, _parsed_tiers
from products.warehouse_sources.backend.migration.types import ItemProposal, ProposedSchema
from products.warehouse_sources.backend.types import ExternalDataSourceType

_TIERS = (
    PriceTier(up_to=1_000_000, unit_amount_usd=Decimal(0)),
    PriceTier(up_to=10_000_000, unit_amount_usd=Decimal("0.000015")),
    PriceTier(up_to=None, unit_amount_usd=Decimal("0.00001")),
)
_SYNC_TYPES: Mapping[ExternalDataSourceType, Mapping[str, str]] = {
    ExternalDataSourceType.HUBSPOT: {"contacts": "incremental", "owners": "full_refresh"},
}


def _connection(
    name: str,
    *,
    source_type: ExternalDataSourceType = ExternalDataSourceType.HUBSPOT,
    tables: Mapping[str, str] | None = None,
    destination_id: str | None = None,
    **proposal: Any,
) -> CostedConnection:
    """`tables` maps each planned Fivetran table to its PostHog table. None plans PostHog's default tables."""
    fields: dict[str, Any] = {
        "source_type": source_type,
        "prefix": name,
        "prefill": {},
        "schemas": None
        if tables is None
        else tuple(
            ProposedSchema(name=posthog, should_sync=True, sync_type=None, vendor_table=vendor)
            for vendor, posthog in tables.items()
        ),
        "sync_frequency": "6hour",
        "sync_time_of_day": None,
        "destination": None,
        **proposal,
    }
    return CostedConnection(
        item_id=f"item_{name}_{destination_id}",
        name=name,
        destination_id=destination_id,
        proposal=ItemProposal(**fields),
    )


def _estimate(connections: list[CostedConnection], usage: list[ReportedUsage], **kwargs: Any) -> CostEstimate:
    return estimate_cost(
        connections,
        usage,
        default_sync_types=lambda source_type: _SYNC_TYPES.get(source_type, {}),
        tiers=kwargs.pop("tiers", _TIERS),
        **kwargs,
    )


_HUBSPOT_TABLES = {"contact": "contacts", "users": "owners"}


class TestEstimateCost(SimpleTestCase):
    @parameterized.expand(
        [
            ("per_table_incremental", {"contact": "contacts"}, [("contact", 1_000)], Confidence.REPORTED, 1_000),
            (
                "full_refresh_table",
                _HUBSPOT_TABLES,
                [("contact", 1_000), ("users", 50)],
                Confidence.ESTIMATED,
                # A full refresh every 6 hours reloads `owners` 120 times a month.
                1_000 + 50 * 120,
            ),
            ("no_table_moves", {}, [(None, 7_000)], Confidence.REPORTED, 0),
            (
                "a_planned_table_without_numbers",
                _HUBSPOT_TABLES,
                [("contact", 1_000)],
                Confidence.ESTIMATED,
                1_000,
            ),
            (
                "an_unplanned_table_is_left_out",
                {"contact": "contacts"},
                [("contact", 1_000), ("email_event", 9_999_999)],
                Confidence.REPORTED,
                1_000,
            ),
            ("connection_total_only", _HUBSPOT_TABLES, [(None, 7_000)], Confidence.ESTIMATED, 7_000),
            ("nothing_reported", _HUBSPOT_TABLES, [], Confidence.UNKNOWN, None),
            ("default_tables", None, [("contact", 1_000)], Confidence.ESTIMATED, 1_000),
        ]
    )
    def test_monthly_rows_per_connection(
        self,
        _name: str,
        tables: Mapping[str, str] | None,
        reported: list[tuple[str | None, int]],
        confidence: Confidence,
        monthly_rows: int | None,
    ) -> None:
        usage = [
            ReportedUsage(connection_name="hubspot", schema_name="hubspot", table_name=table, monthly_rows=rows)
            for table, rows in reported
        ]

        (connection,) = _estimate([_connection("hubspot", tables=tables)], usage).connections

        assert (connection.confidence, connection.monthly_rows) == (confidence, monthly_rows)

    def test_database_tables_match_fivetran_destination_schemas(self) -> None:
        database = _connection(
            "prod_db",
            source_type=ExternalDataSourceType.POSTGRES,
            tables={"public.orders": "public.orders", "billing.invoices": "billing.invoices"},
        )
        usage = [
            ReportedUsage(
                connection_name="PROD_DB", schema_name="prod_db_public", table_name="orders", monthly_rows=10
            ),
            ReportedUsage(
                connection_name="prod_db", schema_name="prod_db_billing", table_name="invoices", monthly_rows=5
            ),
        ]

        (connection,) = _estimate([database], usage).connections

        assert connection.monthly_rows == 15
        assert connection.confidence == Confidence.ESTIMATED

    def test_paused_connection_costs_nothing(self) -> None:
        usage = [ReportedUsage(connection_name="hubspot", table_name="contact", monthly_rows=1_000)]

        (connection,) = _estimate(
            [_connection("hubspot", tables=_HUBSPOT_TABLES, start_paused=True)], usage
        ).connections

        assert connection.monthly_rows == 0

    def test_usage_matches_one_connection_or_is_returned_unmatched(self) -> None:
        connections = [
            _connection("shop", tables=_HUBSPOT_TABLES, destination_id="dest_eu"),
            _connection("shop", tables=_HUBSPOT_TABLES, destination_id="dest_us"),
        ]
        no_destination = ReportedUsage(connection_name="shop", table_name="contact", monthly_rows=3)
        unknown = ReportedUsage(connection_name="no_such_connection", monthly_rows=4)
        skipped = ReportedUsage(connection_name="skipped_one", monthly_rows=5)
        usage = [
            ReportedUsage(connection_name="shop", destination_id="dest_us", table_name="contact", monthly_rows=2),
            no_destination,
            unknown,
            skipped,
        ]

        estimate = _estimate(connections, usage, left_out_names=["skipped_one"])

        assert [(c.item_id, c.monthly_rows) for c in estimate.connections] == [
            ("item_shop_dest_eu", None),
            ("item_shop_dest_us", 2),
        ]
        assert estimate.unmatched_usage == (no_destination, unknown)

    def test_usage_of_a_skipped_connection_with_the_same_name_is_dropped(self) -> None:
        kept = _connection("shop", tables=None, destination_id="dest_us")
        usage = [
            ReportedUsage(connection_name="shop", destination_id="dest_eu", monthly_rows=9),
            ReportedUsage(connection_name="shop", destination_id="dest_us", monthly_rows=2),
        ]

        estimate = _estimate([kept], usage, left_out_names=["shop"])

        assert [c.monthly_rows for c in estimate.connections] == [2]
        assert estimate.unmatched_usage == ()

    @parameterized.expand(
        [
            ("inside_the_free_tier", 400_000, 600_000, Decimal("0.00")),
            # 9M past the free million at $0.000015, then 2M at $0.00001.
            ("across_three_tiers", 6_000_000, 6_000_000, Decimal("155.00")),
        ]
    )
    def test_price_is_split_by_rows_and_adds_up(
        self, _name: str, first_rows: int, second_rows: int, total: Decimal
    ) -> None:
        connections = [_connection(name, tables=None) for name in ("first", "second")]
        usage = [
            ReportedUsage(connection_name="first", monthly_rows=first_rows),
            ReportedUsage(connection_name="second", monthly_rows=second_rows),
        ]

        estimate = _estimate(connections, usage)

        assert estimate.monthly_cost_usd == total
        assert [c.monthly_cost_usd for c in estimate.connections] == [total / 2, total / 2]

    def test_rows_without_prices_when_billing_is_unreadable(self) -> None:
        usage = [ReportedUsage(connection_name="hubspot", monthly_rows=5_000_000)]

        estimate = _estimate([_connection("hubspot", tables=None)], usage, tiers=None)

        assert estimate.monthly_rows == 5_000_000
        assert estimate.monthly_cost_usd is None
        assert estimate.connections[0].monthly_cost_usd is None


class TestPaidTiers(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_warehouse_product", [{"type": "product_analytics", "plans": []}], None),
            ("free_plan_only", [{"type": "data_warehouse", "plans": [{"tiers": None}]}], None),
            (
                "unreadable_price",
                [{"type": "data_warehouse", "plans": [{"tiers": [{"up_to": None, "unit_amount_usd": "n/a"}]}]}],
                None,
            ),
            (
                "paid_plan_after_free_plan",
                [
                    {
                        "type": "data_warehouse",
                        "plans": [
                            {"free_allocation": 1_000_000, "tiers": None},
                            {
                                "tiers": [
                                    {"up_to": 1_000_000, "unit_amount_usd": "0", "flat_amount_usd": "0"},
                                    {"up_to": None, "unit_amount_usd": "0.000015", "flat_amount_usd": "0"},
                                ]
                            },
                        ],
                    }
                ],
                (
                    PriceTier(up_to=1_000_000, unit_amount_usd=Decimal(0)),
                    PriceTier(up_to=None, unit_amount_usd=Decimal("0.000015")),
                ),
            ),
        ]
    )
    def test_reads_the_paid_plan(
        self, _name: str, products: list[dict[str, Any]], expected: tuple[PriceTier, ...] | None
    ) -> None:
        raw_tiers = _paid_plan_tiers(products)

        assert (_parsed_tiers(raw_tiers) if raw_tiers is not None else None) == expected
