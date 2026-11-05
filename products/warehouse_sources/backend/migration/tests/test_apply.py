import dataclasses
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_management import SourceSchema
from products.warehouse_sources.backend.migration.apply import (
    TableOverride,
    TableOverrideError,
    build_planned_schemas,
    with_table_overrides,
)
from products.warehouse_sources.backend.migration.types import (
    ItemProposal,
    ProposedRowFilter,
    ProposedSchema,
    SourceCapabilities,
    VendorColumn,
    VendorRowFilter,
    VendorRowFilterClause,
    VendorTable,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalFieldType


def _proposal(*schemas: ProposedSchema, **overrides: Any) -> ItemProposal:
    fields: dict[str, Any] = {
        "source_type": ExternalDataSourceType.POSTGRES,
        "prefix": "app_db",
        "prefill": {},
        "schemas": schemas,
        "sync_frequency": "6hour",
        "sync_time_of_day": None,
        "destination": None,
        **overrides,
    }
    return ItemProposal(**fields)


def _table(name: str, webhook_only: bool = False, source_schema: str | None = None) -> SourceSchema:
    return SourceSchema(
        name=name,
        webhook_only=webhook_only,
        source_schema=source_schema,
        supports_incremental=True,
        supports_append=True,
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        columns=[("id", "integer", False), ("card_number", "text", True), ("updated_at", "timestamp", True)],
        detected_primary_keys=["id"],
    )


class TestBuildPlannedSchemas(SimpleTestCase):
    def test_overlays_the_plan_on_posthog_defaults(self) -> None:
        proposal = _proposal(
            ProposedSchema(
                name="public.orders",
                should_sync=True,
                sync_type=None,
                disabled_columns=("card_number",),
                row_filters=(
                    ProposedRowFilter(column="status", operator="=", values=("ACTIVE",)),
                    ProposedRowFilter(column="region", operator="IN", values=("eu", "us")),
                ),
            ),
            ProposedSchema(name="public.gone", should_sync=True, sync_type=None),
            ProposedSchema(name="public.locked", should_sync=True, sync_type=None),
        )
        tables = [_table("public.orders"), _table("public.audit_log"), _table("public.locked")]

        planned = build_planned_schemas(proposal, tables, {"public.locked": "permission denied"})

        orders, audit_log, locked = planned.schemas
        assert orders == {
            "name": "public.orders",
            "should_sync": True,
            "sync_type": "incremental",
            "incremental_field": "updated_at",
            "incremental_field_type": "datetime",
            "primary_key_columns": ["id"],
            "enabled_columns": ["id", "updated_at"],
            "row_filters": [
                {"column": "status", "operator": "=", "value": "ACTIVE"},
                {"column": "region", "operator": "IN", "value": ["eu", "us"]},
            ],
            # Set at creation, so no table needs a second update for the planned schedule.
            "sync_frequency": "6hour",
        }
        assert audit_log == {"name": "public.audit_log", "should_sync": False}
        assert locked == {"name": "public.locked", "should_sync": False}
        assert planned.unavailable == ("public.gone", "public.locked")

    def test_an_excluded_column_is_never_the_cursor(self) -> None:
        proposal = _proposal(
            ProposedSchema(name="public.orders", should_sync=True, sync_type=None, disabled_columns=("updated_at",))
        )

        (orders,) = build_planned_schemas(proposal, [_table("public.orders")], {}).schemas

        assert orders["sync_type"] == "full_refresh"
        assert "incremental_field" not in orders
        assert orders["enabled_columns"] == ["id", "card_number"]

    @parameterized.expand(
        [
            ("every_column_excluded", ("id", "card_number", "updated_at"), True),
            # `id` is the detected key, which the reader reads whatever the column selection says.
            ("key_column_excluded", ("id",), True),
            # Discovery lists no columns, so no selection can leave `card_number` out.
            ("columns_unknown", ("card_number",), False),
        ]
    )
    def test_a_table_whose_exclusions_cannot_hold_stays_off(
        self, _name: str, disabled: tuple[str, ...], columns_known: bool
    ) -> None:
        proposal = _proposal(
            ProposedSchema(name="public.orders", should_sync=True, sync_type=None, disabled_columns=disabled)
        )
        table = _table("public.orders")
        if not columns_known:
            table.columns = []

        planned = build_planned_schemas(proposal, [table], {})

        assert planned.schemas == [{"name": "public.orders", "should_sync": False}]
        assert (planned.kept_off, planned.planned) == (("public.orders",), ())

    @parameterized.expand(
        [
            ("no_table_list_uses_posthog_defaults", _proposal(schemas=None), True),
            ("nothing_moves", _proposal(), False),
            (
                "paused",
                _proposal(ProposedSchema(name="public.orders", should_sync=True, sync_type=None), start_paused=True),
                False,
            ),
        ]
    )
    def test_whole_source_decisions(self, _name: str, proposal: ItemProposal, syncs: bool) -> None:
        planned = build_planned_schemas(proposal, [_table("public.orders")], {})
        assert planned.schemas[0]["should_sync"] is syncs
        assert planned.unavailable == ()
        assert bool(planned.planned) == syncs

    def test_matches_alternative_names_and_reports_webhook_only_tables(self) -> None:
        proposal = _proposal(
            ProposedSchema(name="public.orders", should_sync=True, sync_type=None, alternative_names=("orders",)),
            # Discovery read schema `public`, so the bare `users` and `orders` are not this schema's tables.
            ProposedSchema(name="sales.users", should_sync=True, sync_type=None, alternative_names=("users",)),
            ProposedSchema(name="sales.orders", should_sync=True, sync_type=None, alternative_names=("orders",)),
            ProposedSchema(name="events", should_sync=True, sync_type=None),
            sync_time_of_day="03:30:00",
        )
        discovered = [
            _table("orders", source_schema="public"),
            _table("users", source_schema="public"),
            _table("events", webhook_only=True),
        ]

        planned = build_planned_schemas(proposal, discovered, {})

        orders, users, events = planned.schemas
        assert (orders["name"], orders["should_sync"], orders["sync_time_of_day"]) == ("orders", True, "03:30:00")
        assert users == {"name": "users", "should_sync": False}
        assert events == {
            "name": "events",
            "should_sync": False,
            "sync_frequency": "6hour",
            "sync_time_of_day": "03:30:00",
        }
        assert (planned.unavailable, planned.webhook_only, planned.planned) == (
            ("sales.users", "sales.orders"),
            ("events",),
            ("orders", "events"),
        )


_CONTACTS = ProposedSchema(name="contacts", should_sync=True, sync_type=None, vendor_table="contact")
_DEALS = ProposedSchema(name="deals", should_sync=True, sync_type=None, vendor_table="deals")


class TestTableOverrides(SimpleTestCase):
    @parameterized.expand(
        [
            ("rename_an_inferred_pair", [("contact", "contact_list")], ["contact_list", "deals"]),
            ("map_an_unmatched_table", [("email_event", "email_events")], ["contacts", "deals", "email_events"]),
            ("leave_a_table_out", [("deals", None)], ["contacts"]),
            ("swap_two_names", [("contact", "deals"), ("deals", "contacts")], ["deals", "contacts"]),
        ]
    )
    def test_overrides_change_the_plan(
        self, _name: str, overrides: list[tuple[str, str | None]], expected: list[str]
    ) -> None:
        proposal = _proposal(_CONTACTS, _DEALS, unmatched_tables=("email_event",))

        result = with_table_overrides(proposal, [TableOverride(vendor_table=v, posthog_table=p) for v, p in overrides])

        assert result.schemas is not None
        assert [schema.name for schema in result.schemas] == expected

    @parameterized.expand(
        [
            ("unknown_vendor_table", (_CONTACTS,), [("not_a_table", "x")], "not a Fivetran table"),
            ("two_tables_one_name", (_CONTACTS, _DEALS), [("deals", "contacts")], "maps to `contacts`"),
            # The second entry would otherwise replace the first and drop the planned column exclusions.
            ("same_table_twice", (_CONTACTS, _DEALS), [("deals", None), ("deals", "x")], "more than one"),
            ("default_tables_plan", None, [("contact", "x")], "default tables"),
        ]
    )
    def test_overrides_that_do_not_fit_are_refused(
        self,
        _name: str,
        schemas: tuple[ProposedSchema, ...] | None,
        overrides: list[tuple[str, str | None]],
        message: str,
    ) -> None:
        proposal = _proposal(*(schemas or ()), schemas=schemas)
        with self.assertRaisesRegex(TableOverrideError, message):
            with_table_overrides(proposal, [TableOverride(vendor_table=v, posthog_table=p) for v, p in overrides])


_CARD_COLUMN = VendorColumn(name="card_number", enabled=False, hashed=False, is_primary_key=False)


def _vendor_table(*clauses: tuple[str, str, tuple[str, ...]]) -> VendorTable:
    return VendorTable(
        schema_name="hubspot",
        name="email_event",
        enabled=True,
        sync_mode=None,
        columns=(_CARD_COLUMN,),
        row_filter=VendorRowFilter(
            combinator="AND",
            clauses=tuple(VendorRowFilterClause(column=c, operator=o, values=v) for c, o, v in clauses),
        ),
    )


class TestUnmatchedTableRestrictions(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "kept",
                _vendor_table(("status", "EQUALS", ("sent",))),
                (ProposedRowFilter(column="status", operator="=", values=("sent",)),),
                None,
            ),
            ("untranslatable_filter_is_reported", _vendor_table(("status", "LIKE", ("s%",))), (), "row filter"),
            (
                "hashing_loss_is_reported",
                dataclasses.replace(
                    _vendor_table(("status", "EQUALS", ("sent",))),
                    columns=(_CARD_COLUMN, VendorColumn(name="email", enabled=True, hashed=True, is_primary_key=False)),
                ),
                (ProposedRowFilter(column="status", operator="=", values=("sent",)),),
                "hashes some columns",
            ),
        ]
    )
    def test_mapping_an_unmatched_table_keeps_its_restrictions(
        self,
        _name: str,
        vendor_table: VendorTable,
        expected_filters: tuple[ProposedRowFilter, ...],
        expected_caveat: str | None,
    ) -> None:
        caps = SourceCapabilities(
            release_status=None, unreleased=False, supports_column_selection=True, supports_row_filters=True
        )
        caveats: list[str] = []

        result = with_table_overrides(
            _proposal(_CONTACTS, unmatched_tables=("email_event",)),
            [TableOverride(vendor_table="email_event", posthog_table="email_events")],
            vendor_tables={"email_event": vendor_table},
            caps=caps,
            caveats=caveats,
        )

        assert result.schemas is not None
        mapped = result.schemas[-1]
        assert (mapped.disabled_columns, mapped.row_filters) == (("card_number",), expected_filters)
        if expected_caveat:
            assert len(caveats) == 1 and expected_caveat in caveats[0]
        else:
            assert caveats == []
